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
