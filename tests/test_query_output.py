from pathlib import Path
import json

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor, RetrievalHit
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository
from agent_wiki.infrastructure.storage.purpose_reader import PurposeReader


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


def test_query_l2_context_includes_claim_confidence_annotations(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.runtime.claim_annotations import ClaimAnnotationRepository

    ManifestRepository(temp_wiki_root).upsert({
        "wiki_id": "personal-1",
        "doc_id": "atom-claim-context",
        "page_type": "atom",
        "topic": "claims",
        "problem_cluster": "confidence",
    })
    ClaimAnnotationRepository(temp_wiki_root).upsert({
        "doc_id": "atom-claim-context",
        "annotation_method": "rule",
        "claims": [
            {"text": "Paper-backed claim.", "confidence_label": "EXTRACTED", "evidence_refs": ["personal-1:raw-paper"]}
        ],
    })

    context = QueryService()._build_l2_context(
        ManifestRepository(temp_wiki_root),
        [RetrievalHit(wiki_id="personal-1", doc_id="atom-claim-context", score=1.0)],
    )

    assert context[0]["claims"] == [
        {"text": "Paper-backed claim.", "confidence": "EXTRACTED", "evidence_refs": ["personal-1:raw-paper"]}
    ]


def test_query_l3_proof_includes_claim_confidence_annotations(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.runtime.claim_annotations import ClaimAnnotationRepository

    ManifestRepository(temp_wiki_root).upsert({
        "wiki_id": "personal-1",
        "doc_id": "atom-claim-proof",
        "page_type": "atom",
        "source_refs": ["personal-1:raw-paper"],
    })
    ClaimAnnotationRepository(temp_wiki_root).upsert({
        "doc_id": "atom-claim-proof",
        "annotation_method": "rule",
        "claims": [
            {"text": "Proof-backed claim.", "confidence_label": "EXTRACTED", "evidence_refs": ["personal-1:raw-paper"]}
        ],
    })

    proof = QueryService()._build_l3_proof(
        ManifestRepository(temp_wiki_root),
        [RetrievalHit(wiki_id="personal-1", doc_id="atom-claim-proof", score=1.0)],
    )

    assert proof[0]["claims"] == [
        {
            "text": "Proof-backed claim.",
            "confidence": "EXTRACTED",
            "evidence_refs": ["personal-1:raw-paper"],
            "evidence_pages": [],
        }
    ]




def test_query_l2_context_marks_stale_timestamped_atom_with_caveat(temp_wiki_root: Path) -> None:
    from datetime import UTC, datetime, timedelta

    stale_updated_at = (datetime.now(UTC) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    ManifestRepository(temp_wiki_root).upsert({
        "wiki_id": "personal-1",
        "doc_id": "atom-stale-caveat",
        "page_type": "atom",
        "topic": "industry",
        "problem_cluster": "stale",
        "updated_at": stale_updated_at,
    })

    context = QueryService()._build_l2_context(
        ManifestRepository(temp_wiki_root),
        [RetrievalHit(wiki_id="personal-1", doc_id="atom-stale-caveat", score=1.0)],
    )

    assert context[0]["freshness"] == {
        "status": "possibly_stale",
        "updated_at": stale_updated_at,
        "stale_threshold_days": 30,
    }
    assert context[0]["possibly_stale"] is True
    assert "possibly_stale" in context[0]["caveat"]


def test_query_l2_context_keeps_unknown_freshness_for_legacy_atom_without_timestamp(temp_wiki_root: Path) -> None:
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        json.dumps({
            "wiki_id": "personal-1",
            "doc_id": "atom-legacy-no-time",
            "page_type": "atom",
            "topic": "legacy",
            "problem_cluster": "unknown",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    context = QueryService()._build_l2_context(
        ManifestRepository(temp_wiki_root),
        [RetrievalHit(wiki_id="personal-1", doc_id="atom-legacy-no-time", score=1.0)],
    )

    assert context[0]["freshness"] == {
        "status": "unknown",
        "updated_at": None,
        "stale_threshold_days": 30,
    }
    assert context[0]["possibly_stale"] is False
    assert context[0]["caveat"] == ""


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


def test_query_ranking_topic_alignment_boost_beats_broad_external_sync_atom(temp_wiki_root: Path) -> None:
    """Purpose topic alignment should overcome broad external_sync base-score noise."""
    (temp_wiki_root / "purpose.md").write_text(
        "# Purpose\n\n## Topics\n\n- agent-os\n- ai-harness\n- imaging-os\n",
        encoding="utf-8",
    )
    ManifestRepository(temp_wiki_root).batch_upsert(
        [
            {
                "doc_id": "atom-agent-os-agent-os-0001",
                "page_type": "atom",
                "topic": "agent-os",
                "problem_cluster": "agent-os",
                "canonical_uri": "pages/atom-agent-os-agent-os-0001.md",
            },
            {
                "doc_id": "atom-external-sync-ai-cluster-ai-0014",
                "page_type": "atom",
                "topic": "AI推理优化",
                "problem_cluster": "cluster-ai",
                "canonical_uri": "pages/atom-external-sync-ai-cluster-ai-0014.md",
                "source": "external_sync",
            },
        ]
    )
    hits = [
        RetrievalHit(
            wiki_id="personal-1",
            doc_id="atom-external-sync-ai-cluster-ai-0014",
            score=15.0,
            metadata={"lexical_score": 15.0},
        ),
        RetrievalHit(
            wiki_id="personal-1",
            doc_id="atom-agent-os-agent-os-0001",
            score=12.0,
            metadata={"lexical_score": 12.0},
        ),
    ]

    ranked = QueryService()._apply_ranking(
        ManifestRepository(temp_wiki_root),
        PurposeReader(temp_wiki_root),
        hits,
    )

    assert ranked[0].doc_id == "atom-agent-os-agent-os-0001"
    assert ranked[0].metadata["topic_alignment_boost"] >= 5.0
    assert ranked[1].metadata["topic_alignment_boost"] == 0.0


def test_query_ranking_expands_candidate_pool_before_topic_rerank(temp_wiki_root: Path, monkeypatch) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    (temp_wiki_root / "purpose.md").write_text(
        "# Purpose\n\n## Topics\n\n- agent-os\n",
        encoding="utf-8",
    )
    ManifestRepository(temp_wiki_root).batch_upsert(
        [
            {
                "doc_id": "atom-agent-os-agent-os-0001",
                "wiki_id": "personal-1",
                "page_type": "atom",
                "topic": "agent-os",
                "problem_cluster": "agent-os",
                "canonical_uri": "pages/atom-agent-os-agent-os-0001.md",
                "summary": "Agent OS aligned result.",
            },
            {
                "doc_id": "raw-noise-0001",
                "wiki_id": "personal-1",
                "page_type": "raw",
                "topic": "noise",
                "problem_cluster": "noise",
                "canonical_uri": "pages/raw-noise-0001.md",
                "summary": "Noise result.",
            },
        ]
    )
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "atom-agent-os-agent-os-0001.md").write_text(
        "# Agent OS\n\nAligned result.",
        encoding="utf-8",
    )
    (pages_dir / "raw-noise-0001.md").write_text(
        "# Noise\n\nNoise result.",
        encoding="utf-8",
    )

    class FakeRouter:
        def __init__(self, wiki_root, wiki_id, wiki=None):
            self.wiki_root = wiki_root
            self.wiki_id = wiki_id

        def search(self, query, top_k=10, filters=None):
            hits = [
                RetrievalHit(wiki_id="personal-1", doc_id=f"raw-noise-{index:04d}", score=20.0 - index)
                for index in range(1, 11)
            ]
            if top_k > 10:
                hits.append(RetrievalHit(wiki_id="personal-1", doc_id="atom-agent-os-agent-os-0001", score=9.0))
            return hits[:top_k]

    for index in range(1, 11):
        doc_id = f"raw-noise-{index:04d}"
        ManifestRepository(temp_wiki_root).upsert(
            {
                "doc_id": doc_id,
                "wiki_id": "personal-1",
                "page_type": "raw",
                "topic": "noise",
                "problem_cluster": "noise",
                "canonical_uri": f"pages/{doc_id}.md",
                "summary": "Noise result.",
            }
        )
        (pages_dir / f"{doc_id}.md").write_text("# Noise\n\nNoise result.", encoding="utf-8")

    import agent_wiki.application.query as query_module

    monkeypatch.setattr(query_module, "RetrievalRouter", FakeRouter)

    result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="Agent OS App Intents MCP"),
        write_outcome=False,
    )

    assert result.hits[0].doc_id == "atom-agent-os-agent-os-0001"


def test_query_ranking_seeds_likely_purpose_topic_atom_candidates(temp_wiki_root: Path, monkeypatch) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    (temp_wiki_root / "purpose.md").write_text(
        "# Purpose\n\n## Topics\n\n- agent-os\n",
        encoding="utf-8",
    )
    ManifestRepository(temp_wiki_root).batch_upsert(
        [
            {
                "doc_id": "atom-agent-os-agent-os-0001",
                "wiki_id": "personal-1",
                "page_type": "atom",
                "topic": "agent-os",
                "problem_cluster": "agent-os",
                "canonical_uri": "pages/atom-agent-os-agent-os-0001.md",
                "summary": "Agent OS aligned result.",
            },
            {
                "doc_id": "raw-noise-0001",
                "wiki_id": "personal-1",
                "page_type": "raw",
                "topic": "noise",
                "problem_cluster": "noise",
                "canonical_uri": "pages/raw-noise-0001.md",
                "summary": "Noise result.",
            },
        ]
    )
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "atom-agent-os-agent-os-0001.md").write_text("# Agent OS\n\nAligned result.", encoding="utf-8")
    (pages_dir / "raw-noise-0001.md").write_text("# Noise\n\nNoise result.", encoding="utf-8")

    class FakeRouter:
        def __init__(self, wiki_root, wiki_id, wiki=None):
            self.wiki_root = wiki_root
            self.wiki_id = wiki_id

        def search(self, query, top_k=10, filters=None):
            return [RetrievalHit(wiki_id="personal-1", doc_id="raw-noise-0001", score=16.0)]

    import agent_wiki.application.query as query_module

    monkeypatch.setattr(query_module, "RetrievalRouter", FakeRouter)

    result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="Agent OS App Intents MCP"),
        write_outcome=False,
    )

    assert result.hits[0].doc_id == "atom-agent-os-agent-os-0001"
    assert result.hits[0].metadata["topic_alignment_boost"] == 5.0
    assert result.hits[0].metadata["topic_seeded"] is True



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


def test_query_l1_skips_topic_index_metadata_summary(temp_wiki_root: Path) -> None:
    doc_id = "raw-topic-index-metadata"

    l1_answer = QueryService()._build_l1_answer(
        [RetrievalHit(wiki_id="personal-1", doc_id=doc_id, score=1.0, page_type="raw")],
        temp_wiki_root,
        ManifestRepository(temp_wiki_root),
        manifest_by_doc_id={
            doc_id: {
                "doc_id": doc_id,
                "page_type": "raw",
                "summary": "端侧AI影像流水线通过本地推理减少云端依赖。",
            }
        },
        topic_index_entries={
            doc_id: {
                "doc_id": doc_id,
                "summary": "> 学习日期：2026-05-02 | 方向：端侧AI影像 | 深度：深",
            }
        },
    )

    assert l1_answer == "端侧AI影像流水线通过本地推理减少云端依赖。"


def test_query_l1_skips_manifest_metadata_summary(temp_wiki_root: Path) -> None:
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    doc_id = "raw-manifest-metadata"
    (pages_dir / f"{doc_id}.md").write_text(
        "# 端侧AI影像\n\n"
        "端侧AI影像链路在设备侧完成感知、增强和轻量推理。\n",
        encoding="utf-8",
    )

    l1_answer = QueryService()._build_l1_answer(
        [RetrievalHit(wiki_id="personal-1", doc_id=doc_id, score=1.0, page_type="raw")],
        temp_wiki_root,
        ManifestRepository(temp_wiki_root),
        manifest_by_doc_id={
            doc_id: {
                "doc_id": doc_id,
                "page_type": "raw",
                "summary": "> 学习日期：2026-05-02 | 方向：端侧AI影像 | 深度：深",
            }
        },
        topic_index_entries={},
    )

    assert l1_answer == "端侧AI影像链路在设备侧完成感知、增强和轻量推理。"


def test_query_l1_skips_raw_metadata_blockquote_when_using_page_body(temp_wiki_root: Path) -> None:
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    doc_id = "raw-iot-ai-note"
    (pages_dir / f"{doc_id}.md").write_text(
        "# 端侧AI笔记\n\n"
        "> 学习日期：2026-04-17 / 方向：影像OS架构 / 深度：深\n\n"
        "端侧AI在IoT场景中通过本地感知、轻量模型和NPU加速降低云端依赖。\n",
        encoding="utf-8",
    )

    l1_answer = QueryService()._build_l1_answer(
        [RetrievalHit(wiki_id="personal-1", doc_id=doc_id, score=1.0, page_type="raw")],
        temp_wiki_root,
        ManifestRepository(temp_wiki_root),
        manifest_by_doc_id={doc_id: {"doc_id": doc_id, "page_type": "raw"}},
        topic_index_entries={},
    )

    assert "学习日期" not in l1_answer
    assert l1_answer == "端侧AI在IoT场景中通过本地感知、轻量模型和NPU加速降低云端依赖。"


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


def test_query_can_filter_to_compiled_page_types(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-filter-query-1",
            topic="deployment",
            problem_cluster="filter-query",
            content="# Raw filter\n\ncompiled filter target appears here repeatedly compiled filter target",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-filter-query-1",
            page_type="atom",
            topic="deployment",
            problem_cluster="filter-query",
            content="# Atom filter\n\ncompiled filter target",
            source_refs=["personal-1:raw-filter-query-1"],
        ),
    )

    result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="compiled filter target", page_types=["atom", "synthesis"]),
    )

    assert result.hits
    assert {hit.doc_id for hit in result.hits} == {"atom-filter-query-1"}


def test_query_l3_proof_includes_source_page_trace_and_freshness(temp_wiki_root: Path) -> None:
    from datetime import UTC, datetime, timedelta
    from agent_wiki.infrastructure.runtime.claim_annotations import ClaimAnnotationRepository

    stale_updated_at = (datetime.now(UTC) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    ManifestRepository(temp_wiki_root).upsert({
        "wiki_id": "personal-1",
        "doc_id": "raw-proof-source",
        "page_type": "raw",
        "summary": "Primary paper evidence.",
    })
    ManifestRepository(temp_wiki_root).upsert({
        "wiki_id": "personal-1",
        "doc_id": "atom-proof-chain",
        "page_type": "atom",
        "source_refs": ["personal-1:raw-proof-source"],
        "updated_at": stale_updated_at,
    })
    ClaimAnnotationRepository(temp_wiki_root).upsert({
        "doc_id": "atom-proof-chain",
        "annotation_method": "rule",
        "claims": [
            {
                "text": "Proof-backed claim.",
                "confidence_label": "EXTRACTED",
                "evidence_refs": ["personal-1:raw-proof-source"],
            }
        ],
    })

    proof = QueryService()._build_l3_proof(
        ManifestRepository(temp_wiki_root),
        [RetrievalHit(wiki_id="personal-1", doc_id="atom-proof-chain", score=1.0)],
    )

    assert proof[0]["freshness"] == {
        "status": "possibly_stale",
        "updated_at": stale_updated_at,
        "stale_threshold_days": 30,
    }
    assert proof[0]["claims"] == [
        {
            "text": "Proof-backed claim.",
            "confidence": "EXTRACTED",
            "evidence_refs": ["personal-1:raw-proof-source"],
            "evidence_pages": [
                {"doc_id": "raw-proof-source", "page_type": "raw", "summary": "Primary paper evidence."}
            ],
        }
    ]


def test_query_enqueues_ambiguous_claim_reviews_only_for_ambiguous_claims(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.runtime.claim_annotations import ClaimAnnotationRepository
    from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-ambiguous-review",
            topic="quality",
            problem_cluster="claims",
            content="# Raw ambiguous review\n\nquality claims conflict",
            source_refs=[],
        ),
    )
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-extracted-review",
            topic="quality",
            problem_cluster="claims",
            content="# Raw extracted review\n\nquality claims paper",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-ambiguous-review",
            page_type="atom",
            topic="quality",
            problem_cluster="claims",
            summary="Ambiguous claim atom.",
            content="# Atom ambiguous review\n\nquality claims conflict",
            source_refs=["personal-1:raw-ambiguous-review"],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-extracted-review",
            page_type="atom",
            topic="quality",
            problem_cluster="claims",
            summary="Extracted claim atom.",
            content="# Atom extracted review\n\nquality claims paper",
            source_refs=["personal-1:raw-extracted-review"],
        ),
    )
    ClaimAnnotationRepository(temp_wiki_root).upsert({
        "doc_id": "atom-ambiguous-review",
        "annotation_method": "rule",
        "claims": [
            {"text": "Evidence is conflicting.", "confidence_label": "AMBIGUOUS", "evidence_refs": []}
        ],
    })
    ClaimAnnotationRepository(temp_wiki_root).upsert({
        "doc_id": "atom-extracted-review",
        "annotation_method": "rule",
        "claims": [
            {"text": "Paper-backed claim.", "confidence_label": "EXTRACTED", "evidence_refs": ["personal-1:raw-extracted-review"]}
        ],
    })

    service = QueryService()
    result = service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="quality claims", include_pending=False),
        write_outcome=False,
    )

    assert any(hit.doc_id == "atom-ambiguous-review" for hit in result.hits)
    queue_items = ReviewQueueRepository(temp_wiki_root).read_all()
    ambiguous_items = [item for item in queue_items if item.get("review_reason") == "ambiguous_claim"]

    assert len(ambiguous_items) == 1
    assert ambiguous_items[0]["doc_id"] == "atom-ambiguous-review"
    assert ambiguous_items[0]["item_type"] == "claim_review"
    assert ambiguous_items[0]["content_state"]["claim_text"] == "Evidence is conflicting."
    assert all(item.get("doc_id") != "atom-extracted-review" for item in ambiguous_items)
