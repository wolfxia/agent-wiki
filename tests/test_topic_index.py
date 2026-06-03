from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

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


def test_structured_index_prefilters_unrelated_large_rows(temp_wiki_root: Path, monkeypatch) -> None:
    import agent_wiki.infrastructure.retrieval.topic_index as topic_index_module

    repository = TopicIndexRepository(temp_wiki_root)
    for index in range(100):
        repository.upsert(
            {
                "doc_id": f"raw-topic-large-{index:04d}",
                "page_type": "raw",
                "topic": "misc",
                "problem_cluster": "misc",
                "summary": "unrelated summary text " * 50,
            }
        )
    repository.upsert(
        {
            "doc_id": "atom-topic-target",
            "page_type": "atom",
            "topic": "deployment",
            "problem_cluster": "canary",
            "summary": "canary rollout strategy",
        }
    )
    tokenized_texts: list[str] = []
    original_tokenize = topic_index_module.tokenize

    def counting_tokenize(text: str):
        tokenized_texts.append(text)
        return original_tokenize(text)

    monkeypatch.setattr(topic_index_module, "tokenize", counting_tokenize)

    hits = StructuredIndexProvider(temp_wiki_root, wiki_id="personal-1").search("canary rollout", top_k=5)

    assert hits[0].doc_id == "atom-topic-target"
    assert len(tokenized_texts) < 25


def test_structured_index_prefilter_ignores_short_common_terms(temp_wiki_root: Path, monkeypatch) -> None:
    import agent_wiki.infrastructure.retrieval.topic_index as topic_index_module

    repository = TopicIndexRepository(temp_wiki_root)
    for index in range(100):
        repository.upsert(
            {
                "doc_id": f"raw-common-large-{index:04d}",
                "page_type": "raw",
                "topic": "AI OS common",
                "problem_cluster": "misc",
                "summary": "AI OS unrelated summary",
            }
        )
    repository.upsert(
        {
            "doc_id": "atom-rtos-target",
            "page_type": "atom",
            "topic": "RTOS kernel",
            "problem_cluster": "virtualization",
            "summary": "RTOS AI OS kernel virtualization",
        }
    )
    tokenized_texts: list[str] = []
    original_tokenize = topic_index_module.tokenize

    def counting_tokenize(text: str):
        tokenized_texts.append(text)
        return original_tokenize(text)

    monkeypatch.setattr(topic_index_module, "tokenize", counting_tokenize)

    hits = StructuredIndexProvider(temp_wiki_root, wiki_id="personal-1").search("RTOS AI OS", top_k=5)

    assert hits[0].doc_id == "atom-rtos-target"
    assert len(tokenized_texts) < 25



def test_topic_index_repository_deletes_rows_by_doc_id(temp_wiki_root: Path) -> None:
    repository = TopicIndexRepository(temp_wiki_root)
    repository.upsert({"doc_id": "raw-1", "page_type": "raw", "topic": "ops", "problem_cluster": "ops", "summary": "one"})
    repository.upsert({"doc_id": "raw-2", "page_type": "raw", "topic": "ops", "problem_cluster": "ops", "summary": "two"})

    assert repository.delete("raw-1") is True
    assert repository.find("raw-1") is None
    assert repository.find("raw-2") is not None
    assert repository.delete("raw-missing") is False


def test_topic_index_repository_preserves_concurrent_upserts(temp_wiki_root: Path) -> None:
    def upsert_row(index: int) -> None:
        TopicIndexRepository(temp_wiki_root).upsert(
            {
                "doc_id": f"atom-concurrent-{index}",
                "page_type": "atom",
                "topic": "concurrency",
                "problem_cluster": "index",
                "summary": f"summary {index}",
            }
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(upsert_row, range(40)))

    doc_ids = {row["doc_id"] for row in TopicIndexRepository(temp_wiki_root).read_all()}

    assert doc_ids == {f"atom-concurrent-{index}" for index in range(40)}
