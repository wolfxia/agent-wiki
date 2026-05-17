from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_capture_compile_query_chain_returns_compiled_hit(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_result = CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-combo-1",
            topic="combo",
            problem_cluster="combo-chain",
            content="# Raw combo\n\nCapture evidence for combo chain.",
            source_refs=[],
        ),
    )

    compile_result = CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-combo-1",
            page_type="atom",
            topic="combo",
            problem_cluster="combo-chain",
            content="# Atom combo\n\nCompiled combo chain evidence is queryable.",
            source_refs=["personal-1:raw-combo-1"],
        ),
    )

    query_result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="queryable combo chain evidence"),
    )

    assert capture_result.status == "committed"
    assert compile_result.status == "committed"
    assert (temp_wiki_root / "pages" / "raw-combo-1.md").exists()
    assert (temp_wiki_root / "pages" / "atom-combo-1.md").exists()
    assert query_result.hit_count >= 1
    assert query_result.hits[0].doc_id == "atom-combo-1"
    assert query_result.l3_proof[0]["source_refs"] == ["personal-1:raw-combo-1"]
