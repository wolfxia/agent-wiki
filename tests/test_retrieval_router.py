from pathlib import Path

from agent_wiki.application.retrieval_router import RetrievalRouter
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import RetrievalHit
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


def test_retrieval_router_rrf_fuses_fts_and_semantic_ranks(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    router = RetrievalRouter(temp_wiki_root, wiki_id="personal-1", wiki=wiki)

    router.graph.search = lambda query, top_k=10: []  # type: ignore[method-assign]
    router.structured.search = lambda query, top_k=10: []  # type: ignore[method-assign]
    router.fts.search = lambda query, top_k=10, filters=None: [  # type: ignore[method-assign]
        RetrievalHit(wiki_id="personal-1", doc_id="doc-fts-1", score=9.0, section="fts5", metadata={}),
        RetrievalHit(wiki_id="personal-1", doc_id="doc-both", score=8.0, section="fts5", metadata={}),
    ]
    router.lexical.search = lambda wiki_root, query: []  # type: ignore[method-assign]

    class FakeEmbeddingProvider:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0]]

    class FakeVectorIndex:
        def search(self, query_embedding, top_k, filters=None):
            return [
                RetrievalHit(wiki_id="personal-1", doc_id="doc-sem-1", score=0.91, section="vector", metadata={"semantic_score": 0.91}),
                RetrievalHit(wiki_id="personal-1", doc_id="doc-both", score=0.85, section="vector", metadata={"semantic_score": 0.85}),
            ]

    router.embedding_provider = FakeEmbeddingProvider()
    router.vector_index = FakeVectorIndex()

    hits = router.search("camera trend", top_k=3)

    assert [hit.doc_id for hit in hits] == ["doc-both", "doc-fts-1", "doc-sem-1"]
    both = hits[0]
    assert both.metadata["rrf_score"] > 0.0
    assert both.metadata["lexical_score"] > 0.0
    assert both.metadata["semantic_score"] > 0.0


def test_retrieval_router_keeps_fts_only_behavior_without_embedding_config(temp_wiki_root: Path) -> None:
    router = RetrievalRouter(temp_wiki_root, wiki_id="personal-1")
    router.graph.search = lambda query, top_k=10: []  # type: ignore[method-assign]
    router.structured.search = lambda query, top_k=10: []  # type: ignore[method-assign]
    router.fts.search = lambda query, top_k=10, filters=None: [  # type: ignore[method-assign]
        RetrievalHit(wiki_id="personal-1", doc_id="fts-only", score=6.0, section="fts5", metadata={}),
    ]
    router.lexical.search = lambda wiki_root, query: []  # type: ignore[method-assign]

    hits = router.search("no embedding", top_k=3)

    assert [hit.doc_id for hit in hits] == ["fts-only"]
    assert hits[0].metadata["lexical_score"] == 6.0
    assert hits[0].metadata.get("semantic_score", 0.0) == 0.0
