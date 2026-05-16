from pathlib import Path
from shutil import copytree

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import CrossWikiQueryService, QueryInput
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_cross_wiki_query_returns_hits_from_multiple_wikis(tmp_path: Path) -> None:
    personal_root = tmp_path / "sample_wiki"
    shared_root = tmp_path / "shared_wiki"
    copytree(Path("tests/fixtures/sample_wiki"), personal_root)
    copytree(Path("tests/fixtures/shared_wiki"), shared_root)

    registry = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml"))
    personal = registry.wikis[0].model_copy(update={"workspace_path": str(personal_root)})
    shared = registry.wikis[1].model_copy(update={"workspace_path": str(shared_root)})

    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = CrossWikiQueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=personal,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-cross-1",
            topic="testing",
            problem_cluster="cluster-cross",
            content="# Raw cross source",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=personal,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-cross-1",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-cross",
            content="# Atom cross one\n\nLexical baseline is useful.",
            source_refs=["personal-1:raw-cross-1"],
        ),
    )
    compile_service.apply(
        wiki=shared,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="synthesis-cross-1",
            page_type="synthesis",
            topic="testing",
            problem_cluster="cluster-cross",
            content="# Shared synthesis\n\nLexical baseline also appears here.",
            source_refs=["shared-1:raw-proxy"],
            allow_shared_write_without_sources=True,
        ),
    )

    result = query_service.execute([personal, shared], actor, QueryInput(query="lexical baseline"))

    wiki_ids = {hit.wiki_id for hit in result.hits}
    assert "personal-1" in wiki_ids
    assert "shared-1" in wiki_ids
