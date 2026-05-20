from __future__ import annotations

from pathlib import Path

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.infrastructure.retrieval.knowledge_graph import KnowledgeGraphRetrievalProvider
from agent_wiki.infrastructure.retrieval.retrieval_index import LexicalRetrievalProvider, RetrievalIndexRepository
from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider
from agent_wiki.infrastructure.retrieval.topic_index import StructuredIndexProvider


class RetrievalRouter:
    def __init__(self, wiki_root: Path, wiki_id: str) -> None:
        self.graph = KnowledgeGraphRetrievalProvider(wiki_root, wiki_id=wiki_id)
        self.structured = StructuredIndexProvider(wiki_root, wiki_id=wiki_id)
        self.fts = SQLiteFTSIndexProvider(wiki_root, wiki_id=wiki_id)
        self.lexical = LexicalRetrievalProvider(RetrievalIndexRepository)
        self.wiki_root = wiki_root

    def search(self, query: str, top_k: int = 10, filters: dict | None = None) -> list[RetrievalHit]:
        merged: dict[str, RetrievalHit] = {}

        for hit in self.graph.search(query, top_k=top_k):
            merged[hit.doc_id] = self._with_scores(
                hit,
                lexical_score=0.0,
                structured_score=0.0,
                graph_score=hit.score,
                section="knowledge_graph",
            )

        fts_hits = self.fts.search(query, top_k=top_k, filters=filters)
        lexical_hits = fts_hits or self.lexical.search(self.wiki_root, query)
        for hit in lexical_hits:
            existing = merged.get(hit.doc_id)
            graph_score = float(existing.metadata.get("graph_score", 0.0)) if existing else 0.0
            base_hit = existing if existing and existing.section == "knowledge_graph" else hit
            merged[hit.doc_id] = self._with_scores(
                base_hit,
                lexical_score=hit.score,
                structured_score=0.0,
                graph_score=graph_score,
                section=base_hit.section or "lexical",
            )

        for hit in self.structured.search(query, top_k=top_k):
            existing = merged.get(hit.doc_id)
            lexical_score = float(existing.metadata.get("lexical_score", 0.0)) if existing else 0.0
            graph_score = float(existing.metadata.get("graph_score", 0.0)) if existing else 0.0
            structured_score = hit.score
            base_hit = existing if existing and existing.section == "knowledge_graph" else hit
            merged[hit.doc_id] = self._with_scores(
                base_hit,
                lexical_score=lexical_score,
                structured_score=structured_score,
                graph_score=graph_score,
                section=base_hit.section or "topic_index",
            )

        hits = list(merged.values())
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def _with_scores(
        self,
        hit: RetrievalHit,
        *,
        lexical_score: float,
        structured_score: float,
        graph_score: float = 0.0,
        section: str,
    ) -> RetrievalHit:
        capped_graph_score = min(graph_score, 5.0)
        final_score = lexical_score + structured_score + capped_graph_score
        metadata = {
            **hit.metadata,
            "lexical_score": lexical_score,
            "structured_score": structured_score,
            "graph_score": capped_graph_score,
            "raw_graph_score": graph_score,
            "final_score": final_score,
        }
        return hit.model_copy(update={"score": final_score, "section": section, "metadata": metadata})
