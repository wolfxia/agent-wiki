from pathlib import Path

from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider


def test_sqlite_fts_upsert_search_and_delete(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")

    provider.upsert(
        "raw-fts-1",
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-fts-1",
            "page_type": "raw",
            "topic": "deployment",
            "problem_cluster": "canary",
            "summary": "Canary rollout checklist",
            "content": "Use staged canary rollout for risky deploys.",
            "sensitivity": "public",
        },
    )

    hits = provider.search("canary rollout", top_k=5)

    assert (temp_wiki_root / ".agent-wiki" / "retrieval.db").exists()
    assert hits
    assert hits[0].doc_id == "raw-fts-1"
    assert hits[0].section == "fts5"

    provider.delete("raw-fts-1")

    assert provider.search("canary rollout", top_k=5) == []


def test_sqlite_fts_upsert_is_idempotent(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    payload = {
        "wiki_id": "personal-1",
        "doc_id": "raw-fts-1",
        "page_type": "raw",
        "topic": "ops",
        "problem_cluster": "cleanup",
        "summary": "Old summary",
        "content": "old searchable content",
    }

    provider.upsert("raw-fts-1", payload)
    provider.upsert("raw-fts-1", {**payload, "summary": "New summary", "content": "new searchable content"})

    hits = provider.search("searchable", top_k=10)

    assert [hit.doc_id for hit in hits] == ["raw-fts-1"]


def test_sqlite_fts_batch_upsert_reuses_schema_and_connection(temp_wiki_root: Path, monkeypatch) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    ensure_calls = 0
    connect_calls = 0
    original_ensure_schema = provider._ensure_schema
    original_connect = provider._connect

    def counting_ensure_schema() -> None:
        nonlocal ensure_calls
        ensure_calls += 1
        original_ensure_schema()

    def counting_connect():
        nonlocal connect_calls
        connect_calls += 1
        return original_connect()

    monkeypatch.setattr(provider, "_ensure_schema", counting_ensure_schema)
    monkeypatch.setattr(provider, "_connect", counting_connect)

    provider.batch_upsert(
        [
            (
                "raw-batch-1",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "raw-batch-1",
                    "page_type": "raw",
                    "topic": "ops",
                    "problem_cluster": "batch",
                    "content": "first batch searchable",
                },
            ),
            (
                "raw-batch-2",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "raw-batch-2",
                    "page_type": "raw",
                    "topic": "ops",
                    "problem_cluster": "batch",
                    "content": "second batch searchable",
                },
            ),
        ]
    )

    assert ensure_calls == 1
    assert connect_calls == 2
    assert {hit.doc_id for hit in provider.search("batch searchable", top_k=10)} == {"raw-batch-1", "raw-batch-2"}


def test_sqlite_fts_write_normalized_uses_explicit_transaction(temp_wiki_root: Path, monkeypatch) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    calls: list[str] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, statement, params=None):
            calls.append(statement)

        def executemany(self, statement, params):
            calls.append(statement)

    monkeypatch.setattr(provider, "_connect", lambda: FakeConnection())

    provider._write_normalized(
        [
            {
                "doc_id": "raw-explicit-txn",
                "wiki_id": "personal-1",
                "page_type": "raw",
                "topic": "ops",
                "problem_cluster": "txn",
                "summary": "",
                "content": "transaction content",
                "tokens": "transaction content",
                "sensitivity": "",
                "updated_at": "1",
            }
        ]
    )

    assert calls[0] == "BEGIN IMMEDIATE"


def test_sqlite_fts_rebuilds_from_manifest_pages(temp_wiki_root: Path) -> None:
    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "raw-keep.md").write_text("# Keep\n\nFTS rebuild content.", encoding="utf-8")
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    provider.upsert("raw-stale", {"wiki_id": "personal-1", "doc_id": "raw-stale", "content": "stale"})

    provider.rebuild_from_manifest([
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-keep",
            "page_type": "raw",
            "topic": "ops",
            "problem_cluster": "cleanup",
            "summary": "keep summary",
            "canonical_uri": "pages/raw-keep.md",
        }
    ])

    assert [hit.doc_id for hit in provider.search("rebuild", top_k=10)] == ["raw-keep"]
    assert provider.search("stale", top_k=10) == []


def test_sqlite_fts_uses_pre_tokenized_text_for_chinese_terms(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.retrieval.tokenizer import JiebaTokenizer

    class FakeTokenizer:
        def tokenize(self, text: str) -> list[str]:
            return ["鸿蒙", "策略"] if "鸿蒙" in text else [text]

    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1", tokenizer=FakeTokenizer())
    provider.upsert(
        "raw-harmony",
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-harmony",
            "page_type": "raw",
            "topic": "鸿蒙策略",
            "problem_cluster": "OS",
            "summary": "鸿蒙生态策略",
            "content": "鸿蒙策略不应该被错误切成蒙策。",
        },
    )

    hits = provider.search("鸿蒙", top_k=5)

    assert hits
    assert hits[0].doc_id == "raw-harmony"
    assert isinstance(JiebaTokenizer(), JiebaTokenizer)


def test_sqlite_fts_scores_cjk_narrow_topic_above_broad_os_atom(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    # reference_rank=1.0: log curve now has real discrimination
    # BM25 strength=0.1 → 4*log10(1.1) ≈ 0.17; strength=10 → 4*log10(11) ≈ 4.2
    assert 0.0 < provider._score_from_rank(-0.1) < 1.0
    assert 3.0 < provider._score_from_rank(-10.0) < 6.0
    assert 0.0 < provider._score_from_rank(-0.001) < provider._score_from_rank(-0.1)
    assert provider._score_from_rank(-10.0) > provider._score_from_rank(-0.1)
    provider.batch_upsert(
        [
            (
                "atom-os-industry",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "atom-os-industry",
                    "page_type": "atom",
                    "topic": "全球OS竞争格局",
                    "problem_cluster": "os-industry",
                    "summary": "OS生态开发与行业趋势。",
                    "content": "全球OS竞争与移动操作系统生态。",
                },
            ),
            (
                "atom-harmonyos-evolution",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "atom-harmonyos-evolution",
                    "page_type": "atom",
                    "topic": "HarmonyOS 鸿蒙OS演进历程",
                    "problem_cluster": "harmonyos",
                    "summary": "鸿蒙OS从分布式能力到生态建设的演进历程。",
                    "content": "HarmonyOS 鸿蒙系统演进、方舟和分布式软总线。",
                },
            ),
        ]
    )

    hits = provider.search("鸿蒙OS演进历程", top_k=10)

    scores = {hit.doc_id: hit.score for hit in hits}
    assert hits[0].doc_id == "atom-harmonyos-evolution"
    assert 0.0 < scores["atom-harmonyos-evolution"] <= 20.0
    if "atom-os-industry" in scores:
        assert 0.0 <= scores["atom-os-industry"] < scores["atom-harmonyos-evolution"]
        assert scores["atom-harmonyos-evolution"] - scores["atom-os-industry"] >= 0.5
        assert scores["atom-harmonyos-evolution"] >= scores["atom-os-industry"] * 2.0


def test_sqlite_fts_weights_topic_and_summary_above_body_repetition(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    provider.batch_upsert(
        [
            (
                "atom-field-weighted",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "atom-field-weighted",
                    "page_type": "atom",
                    "topic": "canary rollout",
                    "problem_cluster": "deployment",
                    "summary": "Canary rollout deployment strategy.",
                    "content": "Short body.",
                },
            ),
            (
                "raw-body-repeated",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "raw-body-repeated",
                    "page_type": "raw",
                    "topic": "misc",
                    "problem_cluster": "misc",
                    "summary": "misc",
                    "content": "canary rollout canary rollout canary rollout canary rollout",
                },
            ),
        ]
    )

    hits = provider.search("canary rollout", top_k=5)

    assert [hit.doc_id for hit in hits[:2]] == ["atom-field-weighted", "raw-body-repeated"]
    assert hits[0].metadata["fts_rank"] < hits[1].metadata["fts_rank"]


def test_sqlite_fts_filters_by_page_type_and_page_types(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    provider.batch_upsert(
        [
            ("raw-filtered", {"wiki_id": "personal-1", "doc_id": "raw-filtered", "page_type": "raw", "content": "filter target"}),
            ("atom-filtered", {"wiki_id": "personal-1", "doc_id": "atom-filtered", "page_type": "atom", "content": "filter target"}),
            ("synthesis-filtered", {"wiki_id": "personal-1", "doc_id": "synthesis-filtered", "page_type": "synthesis", "content": "filter target"}),
        ]
    )

    atom_hits = provider.search("filter target", top_k=5, filters={"page_type": "atom"})
    compiled_hits = provider.search("filter target", top_k=5, filters={"page_types": ["atom", "synthesis"]})

    assert [hit.doc_id for hit in atom_hits] == ["atom-filtered"]
    assert {hit.doc_id for hit in compiled_hits} == {"atom-filtered", "synthesis-filtered"}


def test_sqlite_fts_short_query_uses_prefix_or_fallback(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    provider.upsert(
        "atom-prefix",
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-prefix",
            "page_type": "atom",
            "topic": "deployment",
            "problem_cluster": "canary-rollout",
            "summary": "Canary rollout strategy.",
            "content": "Use canary rollout for staged deployment.",
        },
    )

    hits = provider.search("canar", top_k=5)

    assert hits
    assert hits[0].doc_id == "atom-prefix"


def test_sqlite_fts_long_query_prefers_conjunctive_match_before_broad_or(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    provider.batch_upsert(
        [
            (
                "atom-methodology-target",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "atom-methodology-target",
                    "page_type": "atom",
                    "topic": "methodology frameworks collection",
                    "problem_cluster": "methodology",
                    "summary": "结构化分析 学习方法 framework collection with source count.",
                    "content": "methodology frameworks collection 结构化分析 学习方法 source count",
                },
            ),
            (
                "raw-broad-noise",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "raw-broad-noise",
                    "page_type": "raw",
                    "topic": "misc",
                    "problem_cluster": "noise",
                    "summary": "source count for unrelated collection.",
                    "content": "source count collection source count collection",
                },
            ),
        ]
    )

    hits = provider.search("methodology frameworks collection 结构化分析 学习方法 source count", top_k=5)

    assert hits
    assert hits[0].doc_id == "atom-methodology-target"


def test_sqlite_fts_long_query_builds_conjunctive_match_before_broad_or(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")

    queries = provider._match_queries("methodology frameworks collection 结构化分析 学习方法 source count")

    assert len(queries) >= 2
    assert " AND " in queries[0]
    assert " OR " in queries[-1]


def test_sqlite_fts_score_discrimination_across_relevance_levels(temp_wiki_root: Path) -> None:
    """P0-1: FTS scores must have real discrimination, not all saturating at ceiling."""
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")

    # Strong match: high BM25 strength
    strong = provider._score_from_rank(-20.0)
    # Medium match: moderate BM25 strength
    medium = provider._score_from_rank(-5.0)
    # Weak match: low BM25 strength
    weak = provider._score_from_rank(-0.5)

    # Scores should be strictly ordered
    assert strong > medium > weak

    # Differences should be meaningful (not just ~0.01 apart)
    assert strong - medium >= 1.0
    assert medium - weak >= 0.5

    # No saturation at ceiling for realistic BM25 values
    assert strong < 20.0

    # Discrimination ratio: strong should be at least 3x weak
    assert strong >= weak * 3.0


def test_sqlite_fts_search_returns_page_type_and_problem_cluster_metadata(temp_wiki_root: Path) -> None:
    """P1-6: FTS hits must include page_type and problem_cluster in metadata."""
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    provider.upsert(
        "atom-metadata-test",
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-metadata-test",
            "page_type": "atom",
            "topic": "deployment methodology",
            "problem_cluster": "canary",
            "summary": "Canary deployment methodology.",
            "content": "Canary deployment for staged rollout.",
        },
    )

    hits = provider.search("canary deployment", top_k=5)

    assert hits
    assert hits[0].metadata["page_type"] == "atom"
    assert hits[0].metadata["problem_cluster"] == "canary"
