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
