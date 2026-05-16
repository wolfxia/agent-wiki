from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_query_returns_l1_l2_l3_layers_and_dispute_caveat(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-query-3",
            topic="testing",
            problem_cluster="cluster-q3",
            content="# Raw query three\n\nPrimary evidence.",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-query-3",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-q3",
            content="# Atom query three\n\nThis page is disputed for now.",
            source_refs=["personal-1:raw-query-3"],
            review_status="disputed",
            dispute_reason="conflicting evidence",
        ),
    )

    result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="disputed evidence", include_pending=False),
    )

    assert result.l1_answer
    assert result.l2_context
    assert result.l3_proof
    assert "disputed" in result.l2_context[0]["caveat"]
    assert "conflicting evidence" in result.l2_context[0]["caveat"]
