from typing import Protocol

from pydantic import BaseModel, Field


class ResolvedActor(BaseModel):
    actor_type: str
    actor_id: str
    transport: str


class PermissionDecision(BaseModel):
    allowed: bool
    reason: str


class KnowledgeStore(Protocol):
    def read_page(self, doc_id: str) -> str: ...

    def write_page(self, doc_id: str, content: str) -> None: ...


class RetrievalHit(BaseModel):
    wiki_id: str
    doc_id: str
    score: float
    section: str | None = None


class RetrievalProvider(Protocol):
    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]: ...


class ContentAdapter(Protocol):
    def read(self, source: str) -> dict: ...

    def write(self, target: str, document: dict) -> None: ...
