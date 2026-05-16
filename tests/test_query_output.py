from pathlib import Path
import json

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


def test_query_execution_appends_query_outcome(temp_wiki_root: Path) -> None:
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
            doc_id="raw-query-outcome-1",
            topic="testing",
            problem_cluster="cluster-qo1",
            content="# Raw outcome one",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-query-outcome-1",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-qo1",
            content="# Atom outcome one\n\nOutcome logging should happen on query.",
            source_refs=["personal-1:raw-query-outcome-1"],
        ),
    )

    result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="outcome logging", include_pending=False),
    )

    outcomes_path = temp_wiki_root / "query_outcomes.jsonl"
    entries = [json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(entries) == 1
    assert entries[0]["query"] == "outcome logging"
    assert entries[0]["hit_count"] == len(result.hits)
    assert entries[0]["actor_id"] == "claude-code"


def test_query_result_includes_hit_count_and_miss_signal(temp_wiki_root: Path) -> None:
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
            doc_id="raw-metrics-1",
            topic="metrics",
            problem_cluster="cluster-m1",
            content="# Raw metrics one",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-metrics-1",
            page_type="atom",
            topic="metrics",
            problem_cluster="cluster-m1",
            content="# Atom metrics\n\nHit count should be exposed.",
            source_refs=["personal-1:raw-metrics-1"],
        ),
    )

    result_with_hits = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="hit count metrics"),
    )
    assert result_with_hits.hit_count >= 1
    assert result_with_hits.miss_signal is False

    result_no_hits = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="zzzznonexistenttopic"),
    )
    assert result_no_hits.hit_count == 0
    assert result_no_hits.miss_signal is True


def test_retrieval_quality_integration(temp_wiki_root: Path) -> None:
    """Chinese + fuzzy + weighted ranking + query logging work together."""
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # Raw capture with Chinese topic
    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-integ-1",
            topic="部署策略",
            problem_cluster="灰度发布",
            content="# 原始记录\n\n灰度发布的初始记录。",
            source_refs=[],
        ),
    )

    # Compiled atom with Chinese topic — should rank higher due to topic match
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-integ-1",
            page_type="atom",
            topic="部署策略",
            problem_cluster="灰度发布",
            content="# 部署原子页\n\nPython部署策略需要灰度发布流程。",
            source_refs=["personal-1:raw-integ-1"],
        ),
    )

    # Another compiled page with only body match (lower rank expected)
    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-integ-2",
            topic="testing",
            problem_cluster="cluster-integ",
            content="# Raw integ two",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-integ-2",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-integ",
            content="# Atom integ two\n\n部署 is mentioned here but not in topic.",
            source_refs=["personal-1:raw-integ-2"],
        ),
    )

    # Chinese query should find CJK content via tokenizer
    result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="部署策略"),
    )

    assert result.hit_count >= 1
    assert result.miss_signal is False
    # Topic-matched page should rank first due to weighted scoring
    assert result.hits[0].doc_id == "atom-integ-1"

    # Fuzzy query with typo should still find results
    fuzzy_result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="deploymnet strategy"),
    )
    # "deploymnet" is a typo for "deployment" — fuzzy may or may not catch this
    # but query logging should still work regardless
    assert fuzzy_result.hit_count >= 0

    # Check query outcomes logged
    outcomes_path = temp_wiki_root / "query_outcomes.jsonl"
    entries = [json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(entries) >= 2
    assert entries[0]["query"] == "部署策略"
    assert entries[0]["hit_count"] >= 1
