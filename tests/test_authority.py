from pathlib import Path

from agent_wiki.application.authority import AuthorityService
from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_authority_promotion_succeeds_when_gate_passes(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-auth-1", topic="testing", problem_cluster="cluster-auth",
            content="# Raw auth", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-auth-1", page_type="atom", topic="testing",
            problem_cluster="cluster-auth",
            content="# Atom auth\n\nPromotable content.",
            source_refs=["personal-1:raw-auth-1"],
        ),
    )

    authority_service = AuthorityService()
    result = authority_service.promote(wiki, actor, "atom-auth-1")

    assert result["status"] == "promoted"
    assert result["doc_id"] == "atom-auth-1"
    # Authority log should record the promotion
    authority_log = temp_wiki_root / "authority_log.jsonl"
    assert authority_log.exists()


def test_authority_promotion_blocked_on_gate_failure(temp_wiki_root: Path) -> None:
    from agent_wiki.bootstrap.registry_loader import PermissionConfig

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={
            "workspace_path": str(temp_wiki_root),
            "permissions": [
                PermissionConfig(
                    actor_type="agent",
                    actor_id="low-agent",
                    allowed_operations=["capture_raw", "compile_update", "promote_principle"],
                    max_gate="A",
                    allowed_page_types=["raw", "atom", "synthesis", "principle"],
                )
            ],
        }
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="low-agent", transport="cli")

    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-auth-2", topic="testing", problem_cluster="cluster-auth2",
            content="# Raw auth 2", source_refs=[],
        ),
    )

    authority_service = AuthorityService()
    result = authority_service.promote(wiki, actor, "raw-auth-2")

    assert result["status"] == "blocked"
    assert "gate" in result["reason"].lower()
