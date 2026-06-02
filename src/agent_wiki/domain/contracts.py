from __future__ import annotations
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ResolvedActor(BaseModel):
    actor_type: str
    actor_id: str
    transport: str


class PermissionDecision(BaseModel):
    allowed: bool
    reason: str
    required_gate: str | None = None


@runtime_checkable
class KnowledgeStore(Protocol):
    def read_page(self, doc_id: str) -> str: ...

    def write_page(self, doc_id: str, content: str) -> None: ...


class RetrievalHit(BaseModel):
    wiki_id: str
    doc_id: str
    score: float
    section: str | None = None
    metadata: dict = Field(default_factory=dict)


@runtime_checkable
class RetrievalProvider(Protocol):
    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]: ...


@runtime_checkable
class QueryClassifier(Protocol):
    def classify(self, query: str) -> str: ...


@runtime_checkable
class CompileSuggestionEvaluator(Protocol):
    def evaluate(self, cluster: dict) -> dict: ...


@runtime_checkable
class QualityEvaluator(Protocol):
    def evaluate(self, inputs: dict) -> dict: ...


# EmbeddingProvider lives in extensions/embedding.py (canonical, with dimension attr).
# Re-exported here for backward compatibility.
from agent_wiki.extensions.embedding import EmbeddingProvider  # noqa: E402


@runtime_checkable
class IndexProvider(Protocol):
    def upsert(self, doc_id: str, payload: dict) -> None: ...

    def delete(self, doc_id: str) -> None: ...


@runtime_checkable
class ContentAdapter(Protocol):
    def read(self, source: str) -> dict: ...

    def write(self, target: str, document: dict) -> None: ...
