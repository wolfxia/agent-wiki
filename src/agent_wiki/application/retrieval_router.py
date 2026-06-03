from __future__ import annotations

from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.extensions import create_embedding_provider
from agent_wiki.infrastructure.retrieval import embedding as _embedding_providers
from agent_wiki.infrastructure.retrieval.knowledge_graph import KnowledgeGraphRetrievalProvider
from agent_wiki.infrastructure.retrieval.retrieval_index import LexicalRetrievalProvider, RetrievalIndexRepository
from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider
from agent_wiki.infrastructure.retrieval.topic_index import StructuredIndexProvider
from agent_wiki.infrastructure.retrieval.vector_index import SQLiteVectorIndexProvider

_TRUTH_ZONE_PAGE_TYPE_BOOSTS = {
    "atom": 1.25,
    "synthesis": 1.5,
    "principle": 1.0,
}
_LEXICAL_REFERENCE_SCORE = 4.0
_STRUCTURED_REFERENCE_SCORE = 6.5
_GRAPH_REFERENCE_SCORE = 5.0
_SEMANTIC_REFERENCE_SCORE = 1.0


class RetrievalRouter:
    def __init__(self, wiki_root: Path, wiki_id: str, wiki: WikiConfig | None = None) -> None:
        self.graph = KnowledgeGraphRetrievalProvider(wiki_root, wiki_id=wiki_id)
        self.structured = StructuredIndexProvider(wiki_root, wiki_id=wiki_id)
        self.fts = SQLiteFTSIndexProvider(wiki_root, wiki_id=wiki_id)
        self.lexical = LexicalRetrievalProvider(RetrievalIndexRepository)
        self.wiki_root = wiki_root
        self.external_sync_penalty = self._external_sync_penalty(wiki)
        self.embedding_provider = self._build_embedding_provider(wiki)
        self.vector_index = self._build_vector_index(wiki_root, wiki_id, wiki)

    def search(self, query: str, top_k: int = 10, filters: dict | None = None) -> list[RetrievalHit]:
        merged: dict[str, RetrievalHit] = {}
        lexical_ranked: list[RetrievalHit] = []
        semantic_ranked: list[RetrievalHit] = []

        for hit in self.graph.search(query, top_k=top_k, filters=filters):
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
            lexical_ranked.append(hit)
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

        if self.embedding_provider is not None and self.vector_index is not None:
            try:
                embeddings = self.embedding_provider.embed_texts([query])
                query_embedding = embeddings[0] if embeddings else None
                semantic_hits = (
                    self.vector_index.search(query_embedding, top_k=top_k, filters=filters)
                    if query_embedding is not None
                    else []
                )
            except Exception:
                semantic_hits = []
            for hit in semantic_hits:
                semantic_ranked.append(hit)
                existing = merged.get(hit.doc_id)
                lexical_score = float(existing.metadata.get("lexical_score", 0.0)) if existing else 0.0
                structured_score = float(existing.metadata.get("structured_score", 0.0)) if existing else 0.0
                graph_score = float(existing.metadata.get("raw_graph_score", 0.0)) if existing else 0.0
                base_hit = existing if existing else hit
                merged[hit.doc_id] = self._with_scores(
                    base_hit,
                    lexical_score=lexical_score,
                    structured_score=structured_score,
                    graph_score=graph_score,
                    semantic_score=hit.metadata.get("semantic_score", hit.score),
                    section=base_hit.section or "vector",
                )

        for hit in self.structured.search(query, top_k=top_k):
            existing = merged.get(hit.doc_id)
            lexical_score = float(existing.metadata.get("lexical_score", 0.0)) if existing else 0.0
            semantic_score = float(existing.metadata.get("semantic_score", 0.0)) if existing else 0.0
            graph_score = float(existing.metadata.get("graph_score", 0.0)) if existing else 0.0
            structured_score = hit.score
            base_hit = existing if existing and existing.section == "knowledge_graph" else hit
            merged[hit.doc_id] = self._with_scores(
                base_hit,
                lexical_score=lexical_score,
                structured_score=structured_score,
                graph_score=graph_score,
                semantic_score=semantic_score,
                section=base_hit.section or "topic_index",
            )

        if semantic_ranked:
            self._apply_rrf(merged, lexical_ranked, semantic_ranked)

        self._apply_fusion_scores(merged)

        self._apply_source_penalties(merged)

        hits = list(merged.values())
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def _apply_rrf(
        self,
        merged: dict[str, RetrievalHit],
        lexical_hits: list[RetrievalHit],
        semantic_hits: list[RetrievalHit],
    ) -> None:
        k = 60.0
        lexical_rank = {hit.doc_id: index for index, hit in enumerate(lexical_hits, start=1)}
        semantic_rank = {hit.doc_id: index for index, hit in enumerate(semantic_hits, start=1)}
        for doc_id, hit in list(merged.items()):
            lexical_part = 1.0 / (k + lexical_rank[doc_id]) if doc_id in lexical_rank else 0.0
            semantic_part = 1.0 / (k + semantic_rank[doc_id]) if doc_id in semantic_rank else 0.0
            graph_score = float(hit.metadata.get("graph_score", 0.0))
            structured_score = float(hit.metadata.get("structured_score", 0.0))
            rrf_score = lexical_part + semantic_part + graph_score + structured_score
            metadata = {
                **hit.metadata,
                "rrf_score": rrf_score,
                "lexical_rank": lexical_rank.get(doc_id),
                "semantic_rank": semantic_rank.get(doc_id),
                "final_score": rrf_score,
            }
            merged[doc_id] = hit.model_copy(update={"score": rrf_score, "metadata": metadata})

    def _apply_fusion_scores(self, merged: dict[str, RetrievalHit]) -> None:
        for doc_id, hit in list(merged.items()):
            lexical_score = float(hit.metadata.get("lexical_score", 0.0))
            structured_score = float(hit.metadata.get("structured_score", 0.0))
            semantic_score = float(hit.metadata.get("semantic_score", 0.0))
            graph_score = float(hit.metadata.get("graph_score", 0.0))
            page_type_boost = self._candidate_page_type_boost(hit)
            fusion_lexical = self._normalize_component(lexical_score, _LEXICAL_REFERENCE_SCORE) * 4.0
            fusion_structured = self._normalize_component(structured_score, _STRUCTURED_REFERENCE_SCORE) * 5.0
            fusion_semantic = self._normalize_component(semantic_score, _SEMANTIC_REFERENCE_SCORE) * 2.0
            fusion_graph = self._normalize_component(graph_score, _GRAPH_REFERENCE_SCORE) * 2.0
            final_score = fusion_lexical + fusion_structured + fusion_semantic + fusion_graph + page_type_boost
            metadata = {
                **hit.metadata,
                "fusion_lexical_score": fusion_lexical,
                "fusion_structured_score": fusion_structured,
                "fusion_semantic_score": fusion_semantic,
                "fusion_graph_score": fusion_graph,
                "candidate_page_type_boost": page_type_boost,
                "final_score": final_score,
            }
            merged[doc_id] = hit.model_copy(update={"score": final_score, "metadata": metadata})

    def _normalize_component(self, score: float, reference_score: float) -> float:
        if score <= 0.0 or reference_score <= 0.0:
            return 0.0
        return min(score / reference_score, 1.0)

    def _apply_source_penalties(self, merged: dict[str, RetrievalHit]) -> None:
        for doc_id, hit in list(merged.items()):
            source_type = self._source_type_for_doc_id(doc_id)
            penalty = self.external_sync_penalty if source_type == "external_sync" else 1.0
            final_score = hit.score * penalty
            metadata = {
                **hit.metadata,
                "source_type": source_type,
                "external_sync_penalty_applied": penalty,
                "final_score": final_score,
            }
            merged[doc_id] = hit.model_copy(update={"score": final_score, "metadata": metadata})

    def _external_sync_penalty(self, wiki: WikiConfig | None) -> float:
        if wiki is None:
            return 1.0
        raw = float(getattr(wiki.retrieval, "external_sync_penalty", 1.0))
        if raw <= 0:
            return 1.0
        return raw

    def _source_type_for_doc_id(self, doc_id: str) -> str:
        normalized = str(doc_id).lower().replace("_", "-")
        return "external_sync" if "external-sync" in normalized else "own"

    def _build_embedding_provider(self, wiki: WikiConfig | None):
        if wiki is None or wiki.retrieval.embedding is None:
            return None
        if "embedding" not in set(wiki.retrieval.optional_providers or []):
            return None
        config = wiki.retrieval.embedding
        return create_embedding_provider(config.provider, config)

    def _build_vector_index(self, wiki_root: Path, wiki_id: str, wiki: WikiConfig | None):
        if wiki is None or wiki.retrieval.embedding is None:
            return None
        if "embedding" not in set(wiki.retrieval.optional_providers or []):
            return None
        return SQLiteVectorIndexProvider(wiki_root, wiki_id=wiki_id, dimension=wiki.retrieval.embedding.dimension)

    def _with_scores(
        self,
        hit: RetrievalHit,
        *,
        lexical_score: float,
        structured_score: float,
        graph_score: float = 0.0,
        semantic_score: float = 0.0,
        section: str,
    ) -> RetrievalHit:
        capped_graph_score = min(graph_score, _GRAPH_REFERENCE_SCORE)
        page_type_boost = self._candidate_page_type_boost(hit)
        final_score = lexical_score + structured_score + semantic_score + capped_graph_score + page_type_boost
        metadata = {
            **hit.metadata,
            "lexical_score": lexical_score,
            "structured_score": structured_score,
            "semantic_score": semantic_score,
            "graph_score": capped_graph_score,
            "raw_graph_score": graph_score,
            "candidate_page_type_boost": page_type_boost,
            "final_score": final_score,
        }
        return hit.model_copy(update={"score": final_score, "section": section, "metadata": metadata})

    def _candidate_page_type_boost(self, hit: RetrievalHit) -> float:
        page_type = str(hit.metadata.get("page_type") or getattr(hit, "page_type", "") or "").lower()
        if not page_type:
            normalized_doc_id = hit.doc_id.lower().replace("_", "-")
            for candidate in _TRUTH_ZONE_PAGE_TYPE_BOOSTS:
                if normalized_doc_id.startswith(candidate + "-"):
                    page_type = candidate
                    break
        return _TRUTH_ZONE_PAGE_TYPE_BOOSTS.get(page_type, 0.0)
