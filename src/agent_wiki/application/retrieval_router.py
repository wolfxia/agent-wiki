from __future__ import annotations

from pathlib import Path

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.infrastructure.retrieval.retrieval_index import LexicalRetrievalProvider, RetrievalIndexRepository
from agent_wiki.infrastructure.retrieval.topic_index import StructuredIndexProvider


class RetrievalRouter:
    def __init__(self, wiki_root: Path, wiki_id: str) -> None:
        self.structured = StructuredIndexProvider(wiki_root, wiki_id=wiki_id)
        self.lexical = LexicalRetrievalProvider(RetrievalIndexRepository)
        self.wiki_root = wiki_root

    def search(self, query: str, top_k: int = 10) -> list[RetrievalHit]:
        merged: dict[str, RetrievalHit] = {}

        for hit in self.lexical.search(self.wiki_root, query):
            merged[hit.doc_id] = hit

        for hit in self.structured.search(query, top_k=top_k):
            boosted = hit.model_copy(update={"score": hit.score + 0.25})
            existing = merged.get(hit.doc_id)
            if existing is None or boosted.score > existing.score:
                merged[hit.doc_id] = boosted

        hits = list(merged.values())
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]
