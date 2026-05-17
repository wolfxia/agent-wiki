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
