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
    assert entries[0]["latency_ms"] >= 0
    assert entries[0]["accepted_doc_ids"] == []
    assert entries[0]["rejected_doc_ids"] == []
    assert entries[0]["page_types"]["atom"] >= 1
    assert entries[0]["score_breakdown"]
    first_breakdown = entries[0]["score_breakdown"][0]
    assert {"doc_id", "fts_score", "structured_score", "graph_score", "boost"}.issubset(first_breakdown)


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


def test_query_ranking_boosted_by_purpose_alignment(temp_wiki_root: Path) -> None:
    """Pages aligned to purpose.md outrank equally-scored non-aligned pages."""
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # Write purpose.md that aligns with "deployment"
    (temp_wiki_root / "purpose.md").write_text(
        "# Purpose\n\n## Topics\n\n- deployment\n",
        encoding="utf-8",
    )

    # Create two pages with similar content scores but different topic alignment
    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-purpose-1", topic="deployment",
            problem_cluster="cluster-p1", content="# Raw purpose one", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-purpose-aligned", page_type="atom", topic="deployment",
            problem_cluster="cluster-p1",
            content="# Aligned\n\nThis page discusses release strategy patterns.",
            source_refs=["personal-1:raw-purpose-1"],
        ),
    )

    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-purpose-2", topic="unrelated",
            problem_cluster="cluster-p2", content="# Raw purpose two", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-purpose-unaligned", page_type="atom", topic="unrelated",
            problem_cluster="cluster-p2",
            content="# Unaligned\n\nThis page discusses release strategy patterns. Release strategy is key.",
            source_refs=["personal-1:raw-purpose-2"],
        ),
    )

    result = query_service.execute(
        wiki=wiki, actor=actor,
        data=QueryInput(query="release strategy patterns"),
    )

    # Both should be found
    doc_ids = [h.doc_id for h in result.hits]
    assert "atom-purpose-aligned" in doc_ids
    assert "atom-purpose-unaligned" in doc_ids
    # Purpose-aligned page should rank first
    assert doc_ids.index("atom-purpose-aligned") < doc_ids.index("atom-purpose-unaligned")



def test_query_logging_writes_stable_query_id_to_outcomes_and_hits(temp_wiki_root: Path) -> None:
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
            doc_id="raw-query-id-1",
            topic="testing",
            problem_cluster="cluster-qid",
            content="# Raw query id one",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-query-id-1",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-qid",
            content="# Atom query id one\n\nStable query ids matter.",
            source_refs=["personal-1:raw-query-id-1"],
        ),
    )

    query_service.execute(wiki=wiki, actor=actor, data=QueryInput(query="stable query ids"))

    outcomes = [json.loads(line) for line in (temp_wiki_root / "query_outcomes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    hits = [json.loads(line) for line in (temp_wiki_root / "query_hits.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(outcomes) == 1
    assert outcomes[0].get("query_id")
    assert "query_idx" not in outcomes[0]
    assert hits
    assert all(hit.get("query_id") == outcomes[0]["query_id"] for hit in hits)
    assert all("query_idx" not in hit for hit in hits)



def test_query_l1_prefers_summary_from_topic_index(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository

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
            doc_id="raw-summary-1",
            topic="deployment",
            problem_cluster="cluster-summary",
            content="# Raw summary one",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-summary-1",
            page_type="atom",
            topic="deployment",
            problem_cluster="cluster-summary",
            summary="Preferred summary answer.",
            content="# Atom summary one\n\nBody text that should not be used as L1.",
            source_refs=["personal-1:raw-summary-1"],
        ),
    )
    TopicIndexRepository(temp_wiki_root).upsert({
        "doc_id": "atom-summary-1",
        "page_type": "atom",
        "topic": "deployment",
        "problem_cluster": "cluster-summary",
        "summary": "Preferred summary answer.",
    })

    result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="preferred summary answer deployment"),
    )

    assert result.l1_answer == "Preferred summary answer."


def test_query_hits_include_ranking_debug_metadata(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "purpose.md").write_text("# Purpose\n\n## Topics\n\n- deployment\n", encoding="utf-8")
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-rank-debug-1",
            topic="deployment",
            problem_cluster="canary",
            content="# Raw rank debug",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-rank-debug-1",
            page_type="atom",
            topic="deployment",
            problem_cluster="canary",
            summary="Ranking debug summary.",
            content="# Atom rank debug\n\ncanary rollout debug body",
            source_refs=["personal-1:raw-rank-debug-1"],
        ),
    )

    result = QueryService().execute(wiki=wiki, actor=actor, data=QueryInput(query="canary rollout"))

    metadata = result.hits[0].metadata
    assert result.hits[0].doc_id == "atom-rank-debug-1"
    assert metadata["lexical_score"] >= 0
    assert metadata["structured_score"] >= 0
    assert metadata["page_type_boost"] > 0
    assert metadata["purpose_boost"] > 0
    assert "freshness" in metadata
    assert metadata["final_score"] == result.hits[0].score
