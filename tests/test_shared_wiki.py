from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_shared_wiki_rejects_raw_capture(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml")).wikis[1].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    service = CaptureRawService()

    try:
        service.execute(
            wiki=wiki,
            actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
            data=CaptureRawInput(
                doc_id="raw-shared-1",
                topic="testing",
                problem_cluster="cluster-shared",
                content="# Shared raw",
                source_refs=[],
            ),
        )
    except ValueError as error:
        assert "page type raw is not allowed" in str(error)
    else:
        raise AssertionError("expected shared wiki raw rejection")


def test_shared_wiki_allows_synthesis_update_only(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml")).wikis[1].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    result = service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="synthesis-shared-1",
            page_type="synthesis",
            topic="testing",
            problem_cluster="cluster-shared",
            content="# Shared synthesis",
            source_refs=["shared-1:raw-proxy"],
            allow_shared_write_without_sources=True,
        ),
    )

    assert result.status == "committed"
