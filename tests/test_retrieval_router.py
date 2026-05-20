from pathlib import Path

from agent_wiki.application.retrieval_router import RetrievalRouter
from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository


def test_retrieval_router_prefers_structured_hits(temp_wiki_root: Path) -> None:
    topic_index = TopicIndexRepository(temp_wiki_root)
    topic_index.upsert({
        "doc_id": "atom-structured-1",
        "page_type": "atom",
        "topic": "deployment",
        "problem_cluster": "canary",
        "summary": "Structured summary for canary rollout.",
    })

    lexical = RetrievalIndexRepository(temp_wiki_root)
    lexical.append_compiled_card(
        "personal-1",
        type("CompiledCard", (), {
            "doc_id": "atom-lexical-1",
            "page_type": "atom",
            "topic": "testing",
            "problem_cluster": "fallback",
            "content": "canary rollout appears only in lexical content",
        })(),
    )

    hits = RetrievalRouter(temp_wiki_root, wiki_id="personal-1").search("canary rollout")

    assert hits
    assert hits[0].doc_id == "atom-structured-1"


def test_retrieval_router_falls_back_to_lexical_hits(temp_wiki_root: Path) -> None:
    lexical = RetrievalIndexRepository(temp_wiki_root)
    lexical.append_compiled_card(
        "personal-1",
        type("CompiledCard", (), {
            "doc_id": "atom-fallback-1",
            "page_type": "atom",
            "topic": "testing",
            "problem_cluster": "fallback",
            "content": "fallback retrieval content",
        })(),
    )

    hits = RetrievalRouter(temp_wiki_root, wiki_id="personal-1").search("fallback retrieval")

    assert hits
    assert hits[0].doc_id == "atom-fallback-1"


def test_retrieval_router_uses_sqlite_fts_runtime_index(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider

    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    provider.upsert(
        "raw-runtime-fts",
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-runtime-fts",
            "page_type": "raw",
            "topic": "runtime",
            "problem_cluster": "fts",
            "summary": "Runtime FTS hit",
            "content": "runtime sqlite full text search content",
        },
    )

    hits = RetrievalRouter(temp_wiki_root, wiki_id="personal-1").search("runtime sqlite")

    assert hits
    assert hits[0].doc_id == "raw-runtime-fts"
    assert hits[0].section == "fts5"


def test_retrieval_router_merges_lexical_and_structured_debug_scores(temp_wiki_root: Path) -> None:
    topic_index = TopicIndexRepository(temp_wiki_root)
    topic_index.upsert({
        "doc_id": "atom-debug-1",
        "page_type": "atom",
        "topic": "deployment",
        "problem_cluster": "canary",
        "summary": "Canary rollout summary.",
    })
    lexical = RetrievalIndexRepository(temp_wiki_root)
    lexical.append_compiled_card(
        "personal-1",
        type("CompiledCard", (), {
            "doc_id": "atom-debug-1",
            "page_type": "atom",
            "topic": "deployment",
            "problem_cluster": "canary",
            "content": "canary rollout lexical body",
        })(),
    )

    hit = RetrievalRouter(temp_wiki_root, wiki_id="personal-1").search("canary rollout")[0]

    assert hit.doc_id == "atom-debug-1"
    assert hit.metadata["lexical_score"] > 0
    assert hit.metadata["structured_score"] > 0
    assert hit.metadata["final_score"] == hit.score


def test_retrieval_router_caps_graph_score_below_structured_relevance(temp_wiki_root: Path) -> None:
    from agent_wiki.domain.contracts import RetrievalHit

    router = RetrievalRouter(temp_wiki_root, wiki_id="personal-1")

    graph_only = RetrievalHit(
        wiki_id="personal-1",
        doc_id="raw-graph-edge-only",
        score=10.0,
        page_type="raw",
        snippet="Graph edge match without topic evidence.",
        metadata={},
    )
    structured_relevant = RetrievalHit(
        wiki_id="personal-1",
        doc_id="atom-topic-relevant",
        score=6.0,
        page_type="atom",
        snippet="Structured topic match.",
        metadata={},
    )

    router.graph.search = lambda query, top_k=10: [graph_only]  # type: ignore[method-assign]
    router.fts.search = lambda query, top_k=10, filters=None: []  # type: ignore[method-assign]
    router.lexical.search = lambda wiki_root, query: []  # type: ignore[method-assign]
    router.structured.search = lambda query, top_k=10: [structured_relevant]  # type: ignore[method-assign]

    hits = router.search("端侧AI在IoT上的实践及未来方向")

    assert [hit.doc_id for hit in hits[:2]] == ["atom-topic-relevant", "raw-graph-edge-only"]
    graph_hit = next(hit for hit in hits if hit.doc_id == "raw-graph-edge-only")
    assert graph_hit.metadata["graph_score"] <= 5.0
