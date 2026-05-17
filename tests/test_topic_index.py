from pathlib import Path

from agent_wiki.infrastructure.retrieval.topic_index import StructuredIndexProvider, TopicIndexRepository


def test_topic_index_repository_writes_markdown_rows(temp_wiki_root: Path) -> None:
    repository = TopicIndexRepository(temp_wiki_root)

    repository.upsert({
        "doc_id": "atom-topic-1",
        "page_type": "atom",
        "topic": "deployment",
        "problem_cluster": "canary",
        "summary": "Canary rollout summary.",
    })

    text = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
    assert "| doc_id | page_type | topic | problem_cluster | summary |" in text
    assert "| atom-topic-1 | atom | deployment | canary | Canary rollout summary. |" in text
    rows = repository.read_all()
    assert rows[0]["doc_id"] == "atom-topic-1"


def test_structured_index_provider_returns_hits_by_topic_and_summary(temp_wiki_root: Path) -> None:
    repository = TopicIndexRepository(temp_wiki_root)
    repository.upsert({
        "doc_id": "atom-deploy-1",
        "page_type": "atom",
        "topic": "deployment",
        "problem_cluster": "canary",
        "summary": "Canary rollout summary.",
    })
    repository.upsert({
        "doc_id": "atom-cache-1",
        "page_type": "atom",
        "topic": "caching",
        "problem_cluster": "warming",
        "summary": "Cache warming summary.",
    })

    hits = StructuredIndexProvider(temp_wiki_root, wiki_id="personal-1").search("canary rollout", top_k=5)

    assert hits
    assert hits[0].doc_id == "atom-deploy-1"
    assert hits[0].score > 0
