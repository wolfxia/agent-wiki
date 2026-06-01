from pathlib import Path

import yaml

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.linting import LintService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.extensions import get_page_type_registry, register_page_type
from agent_wiki.infrastructure.identity.permissions import PermissionService


def _registry_with_document_type(tmp_path: Path, wiki_root: Path) -> Path:
    data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text(encoding="utf-8"))
    data["wikis"][0]["workspace_path"] = str(wiki_root)
    data["wikis"][0]["allowed_page_types"] = ["raw", "atom", "synthesis", "principle", "document"]
    for permission in data["wikis"][0]["permissions"]:
        if permission["actor_id"] == "claude-code":
            permission["allowed_page_types"] = ["raw", "atom", "synthesis", "document"]
    registry_path = tmp_path / "registry-document.yaml"
    registry_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return registry_path


def test_register_page_type_makes_custom_type_available_to_registry_and_permissions(tmp_path: Path, temp_wiki_root: Path) -> None:
    register_page_type("document", default_gate="B", requires_source_refs=True, truth_zone=True)
    registry_path = _registry_with_document_type(tmp_path, temp_wiki_root)

    wiki = RegistryLoader().load(registry_path).wikis[0]
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    assert "document" in wiki.allowed_page_types
    assert get_page_type_registry().get("document").truth_zone is True

    decision = PermissionService().check(actor, "compile_update", wiki, "document")

    assert decision.allowed is True
    assert decision.required_gate == "B"


def test_compile_update_accepts_registered_custom_page_type(tmp_path: Path, temp_wiki_root: Path) -> None:
    register_page_type("document", default_gate="B", requires_source_refs=True, truth_zone=True)
    registry_path = _registry_with_document_type(tmp_path, temp_wiki_root)
    wiki = RegistryLoader().load(registry_path).wikis[0]
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-document-source",
            topic="enterprise",
            problem_cluster="documents",
            summary="source",
            content="# Source",
            source_refs=[],
        ),
    )

    result = CompileUpdateService(registry_path=registry_path).apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="document-contract-1",
            page_type="document",
            topic="enterprise",
            problem_cluster="documents",
            summary="Contract document",
            content="# Contract",
            source_refs=["personal-1:raw-document-source"],
        ),
    )

    assert result.status == "committed"
    assert (temp_wiki_root / "pages" / "document-contract-1.md").exists()
    assert LintService().run(wiki).ok is True


def test_registry_rejects_unknown_page_type(tmp_path: Path, temp_wiki_root: Path) -> None:
    registry_path = _registry_with_document_type(tmp_path, temp_wiki_root)
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    data["wikis"][0]["allowed_page_types"] = ["raw", "whitepaper"]
    registry_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    try:
        RegistryLoader().load(registry_path)
    except ValueError as error:
        assert "unknown page type" in str(error)
    else:
        raise AssertionError("expected unknown page type failure")
