from __future__ import annotations

from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.infrastructure.retrieval.embedding import SiliconFlowEmbeddingProvider
from agent_wiki.infrastructure.retrieval.knowledge_graph import KnowledgeGraphRetrievalProvider
from agent_wiki.infrastructure.retrieval.retrieval_index import LexicalRetrievalProvider, RetrievalIndexRepository
from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider
from agent_wiki.infrastructure.retrieval.topic_index import StructuredIndexProvider
from agent_wiki.infrastructure.retrieval.vector_index import SQLiteVectorIndexProvider


class RetrievalRouter:
    def __init__(self, wiki_root: Path, wiki_id: str, wiki: WikiConfig | None = None) -> None:
        self.graph = KnowledgeGraphRetrievalProvider(wiki_root, wiki_id=wiki_id)
        self.structured = StructuredIndexProvider(wiki_root, wiki_id=wiki_id)
        self.fts = SQLiteFTSIndexProvider(wiki_root, wiki_id=wiki_id)
        self.lexical = LexicalRetrievalProvider(RetrievalIndexRepository)
        self.wiki_root = wiki_root
        self.embedding_provider = self._build_embedding_provider(wiki)
        self.vector_index = self._build_vector_index(wiki_root, wiki_id, wiki)

    def search(self, query: str, top_k: int = 10, filters: dict | None = None) -> list[RetrievalHit]:
        merged: dict[str, RetrievalHit] = {}
        lexical_ranked: list[RetrievalHit] = []
        semantic_ranked: list[RetrievalHit] = []

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

    def _build_embedding_provider(self, wiki: WikiConfig | None):
        if wiki is None or wiki.retrieval.embedding is None:
            return None
        if "embedding" not in set(wiki.retrieval.optional_providers or []):
            return None
        config = wiki.retrieval.embedding
        if config.provider != "siliconflow":
            return None
        return SiliconFlowEmbeddingProvider(
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            model=config.model,
            dimension=config.dimension,
            batch_size=config.batch_size,
            timeout_seconds=config.timeout_seconds,
        )

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
        capped_graph_score = min(graph_score, 5.0)
        final_score = lexical_score + structured_score + semantic_score + capped_graph_score
        metadata = {
            **hit.metadata,
            "lexical_score": lexical_score,
            "structured_score": structured_score,
            "semantic_score": semantic_score,
            "graph_score": capped_graph_score,
            "raw_graph_score": graph_score,
            "final_score": final_score,
        }
        return hit.model_copy(update={"score": final_score, "section": section, "metadata": metadata})
