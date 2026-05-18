from pathlib import Path

from typing import runtime_checkable

from agent_wiki.domain.contracts import EmbeddingProvider, IndexProvider, RetrievalProvider
from agent_wiki.infrastructure.retrieval.retrieval_index import LexicalRetrievalProvider, RetrievalIndexRepository


def test_domain_exposes_retrieval_provider_protocols() -> None:
    assert getattr(RetrievalProvider, "_is_protocol", False) is True
    assert getattr(EmbeddingProvider, "_is_protocol", False) is True
    assert getattr(IndexProvider, "_is_protocol", False) is True


def test_lexical_retrieval_provider_is_default_retrieval_implementation() -> None:
    provider = LexicalRetrievalProvider(RetrievalIndexRepository)

    assert isinstance(provider, RetrievalProvider)
    assert provider.repository_cls is RetrievalIndexRepository



def test_retrieval_index_rebuilds_from_manifest_pages(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository

    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "raw-keep.md").write_text("# Keep\n\nSearchable keep content.", encoding="utf-8")
    manifest_entries = [
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-keep",
            "page_type": "raw",
            "topic": "ops",
            "problem_cluster": "cleanup",
            "summary": "keep summary",
            "canonical_uri": "pages/raw-keep.md",
        }
    ]

    repository = RetrievalIndexRepository(temp_wiki_root)
    repository.index_path.write_text('{"wiki_id":"personal-1","doc_id":"raw-stale","content":"stale"}\n', encoding="utf-8")
    repository.rebuild_from_manifest(manifest_entries)

    index_text = repository.index_path.read_text(encoding="utf-8")
    assert "raw-keep" in index_text
    assert "Searchable keep content" in index_text
    assert "raw-stale" not in index_text


def test_lexical_search_handles_legacy_cards_without_wiki_id(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository

    repository = RetrievalIndexRepository(temp_wiki_root)
    repository.index_path.write_text(
        '{"doc_id":"legacy-card","topic":"legacy","problem_cluster":"fallback","content":"legacy fallback query"}\n',
        encoding="utf-8",
    )

    hits = repository.lexical_search("legacy fallback")

    assert hits[0].doc_id == "legacy-card"
    assert hits[0].wiki_id == ""


def test_lexical_search_prefilters_unrelated_large_cards(temp_wiki_root: Path, monkeypatch) -> None:
    from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository
    import agent_wiki.infrastructure.retrieval.retrieval_index as retrieval_index

    repository = RetrievalIndexRepository(temp_wiki_root)
    rows = []
    for index in range(100):
        rows.append(
            '{"wiki_id":"personal-1","doc_id":"raw-large-%04d","topic":"misc","problem_cluster":"misc","content":"%s"}'
            % (index, "unrelated body text " * 200)
        )
    rows.append(
        '{"wiki_id":"personal-1","doc_id":"atom-target","topic":"deployment","problem_cluster":"canary","content":"canary rollout strategy"}'
    )
    repository.index_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    tokenized_texts: list[str] = []
    original_tokenize = retrieval_index.tokenize

    def counting_tokenize(text: str):
        tokenized_texts.append(text)
        return original_tokenize(text)

    monkeypatch.setattr(retrieval_index, "tokenize", counting_tokenize)

    hits = repository.lexical_search("canary rollout")

    assert hits[0].doc_id == "atom-target"
    assert len(tokenized_texts) < 25
