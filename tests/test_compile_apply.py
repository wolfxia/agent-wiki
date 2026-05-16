import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_compile_apply_writes_atom_and_operation_log(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-source-2",
            topic="testing",
            problem_cluster="cluster-b",
            content="# Source two",
            source_refs=[],
        ),
    )

    result = compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-new",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-b",
            content="# Atom new\n\nCompiled",
            source_refs=["personal-1:raw-source-2"],
        ),
    )

    assert result.status == "committed"
    assert (temp_wiki_root / "pages" / "atom-new.md").exists()
    assert (temp_wiki_root / "operation_log.jsonl").exists()
    operation = json.loads((temp_wiki_root / "operation_log.jsonl").read_text().strip())
    assert operation["operation"] == "compile_update"
    assert operation["doc_id"] == "atom-new"


def test_compile_apply_rejects_missing_raw_source_ref(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    try:
        compile_service.apply(
            wiki=wiki,
            actor=actor,
            data=CompileUpdateInput(
                doc_id="atom-invalid",
                page_type="atom",
                topic="testing",
                problem_cluster="cluster-b",
                content="# Invalid",
                source_refs=["personal-1:missing-raw"],
            ),
        )
    except ValueError as error:
        assert "source_refs must point to existing raw pages" in str(error)
    else:
        raise AssertionError("expected source ref validation failure")


def test_compile_apply_denied_when_actor_gate_insufficient(temp_wiki_root: Path) -> None:
    from agent_wiki.bootstrap.registry_loader import PermissionConfig

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={
            "workspace_path": str(temp_wiki_root),
            "permissions": [
                PermissionConfig(
                    actor_type="agent",
                    actor_id="low-gate-agent",
                    allowed_operations=["compile_update"],
                    max_gate="A",
                    allowed_page_types=["atom", "synthesis"],
                )
            ],
        }
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="low-gate-agent", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-gate-1", topic="testing", problem_cluster="cluster-gate",
            content="# Raw gate", source_refs=[],
        ),
    )

    try:
        compile_service.apply(
            wiki=wiki,
            actor=actor,
            data=CompileUpdateInput(
                doc_id="atom-gate-1", page_type="atom", topic="testing",
                problem_cluster="cluster-gate",
                content="# Atom gate",
                source_refs=["personal-1:raw-gate-1"],
            ),
        )
    except PermissionError as error:
        assert "gate" in str(error).lower()
    else:
        raise AssertionError("expected gate enforcement failure")
