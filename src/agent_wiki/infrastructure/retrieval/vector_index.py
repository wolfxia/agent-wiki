from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from agent_wiki.domain.contracts import RetrievalHit


class SQLiteVectorIndexProvider:
    def __init__(self, wiki_root: Path, wiki_id: str, dimension: int = 1024) -> None:
        self.wiki_root = wiki_root
        self.wiki_id = wiki_id
        self.dimension = dimension
        self.db_path = wiki_root / ".agent-wiki" / "vectors.db"

    def upsert(self, doc_id: str, payload: dict) -> None:
        self.batch_upsert([(doc_id, payload)])

    def batch_upsert(self, items: list[tuple[str, dict]]) -> None:
        if not items:
            return
        self._ensure_schema()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for doc_id, payload in items:
                embedding = self._coerce_embedding(payload.get("embedding"))
                connection.execute(
                    """
                    INSERT INTO vectors(doc_id, wiki_id, page_type, embedding, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        wiki_id=excluded.wiki_id,
                        page_type=excluded.page_type,
                        embedding=excluded.embedding,
                        updated_at=excluded.updated_at
                    """,
                    (
                        doc_id,
                        payload.get("wiki_id") or self.wiki_id,
                        payload.get("page_type") or "",
                        embedding.tobytes(),
                        payload.get("updated_at") or "",
                    ),
                )

    def delete(self, doc_id: str) -> None:
        if not self.db_path.exists():
            return
        with self._connect() as connection:
            connection.execute("DELETE FROM vectors WHERE doc_id = ?", (doc_id,))

    def rebuild_from_manifest(self, manifest_entries: list[dict], embedding_provider=None) -> int:
        self._ensure_schema()
        with self._connect() as connection:
            connection.execute("DELETE FROM vectors")
        if embedding_provider is None:
            return 0
        texts: list[str] = []
        payloads: list[dict] = []
        for entry in manifest_entries:
            content = str(entry.get("content") or entry.get("summary") or "")
            if not content:
                continue
            texts.append(content)
            payloads.append(entry)
        embeddings = embedding_provider.embed_texts(texts)
        self.batch_upsert(
            [
                (
                    str(payload.get("doc_id") or ""),
                    {
                        "wiki_id": payload.get("wiki_id") or self.wiki_id,
                        "page_type": payload.get("page_type") or "",
                        "embedding": np.asarray(embedding, dtype=np.float32),
                        "updated_at": payload.get("updated_at") or "",
                    },
                )
                for payload, embedding in zip(payloads, embeddings, strict=True)
                if payload.get("doc_id")
            ]
        )
        return len(payloads)

    def search(self, query_embedding, top_k: int, filters: dict | None = None) -> list[RetrievalHit]:
        if not self.db_path.exists():
            return []
        query = self._coerce_embedding(query_embedding)
        rows = []
        with self._connect() as connection:
            rows = connection.execute("SELECT doc_id, wiki_id, page_type, embedding FROM vectors").fetchall()
        hits: list[RetrievalHit] = []
        for row in rows:
            page_type = row["page_type"] or ""
            if self._page_type_filtered(page_type, filters):
                continue
            embedding = np.frombuffer(row["embedding"], dtype=np.float32)
            score = self._cosine_similarity(query, embedding)
            if score <= 0:
                continue
            hits.append(
                RetrievalHit(
                    wiki_id=row["wiki_id"] or self.wiki_id,
                    doc_id=row["doc_id"],
                    score=float(score),
                    section="vector",
                    metadata={"semantic_score": float(score)},
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def _page_type_filtered(self, page_type: str, filters: dict | None) -> bool:
        if not filters:
            return False
        allowed = filters.get("page_types") or ([filters["page_type"]] if filters.get("page_type") else [])
        return bool(allowed) and page_type not in {str(value) for value in allowed}

    def _cosine_similarity(self, left: np.ndarray, right: np.ndarray) -> float:
        if left.size == 0 or right.size == 0:
            return 0.0
        left = left.astype(np.float32, copy=False)
        right = right.astype(np.float32, copy=False)
        if left.shape != right.shape:
            return 0.0
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator == 0.0:
            return 0.0
        return float(np.dot(left, right) / denominator)

    def _coerce_embedding(self, embedding) -> np.ndarray:
        array = np.asarray(embedding, dtype=np.float32)
        if array.ndim != 1:
            raise ValueError("embedding must be one-dimensional")
        return array

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vectors(
                    doc_id TEXT PRIMARY KEY,
                    wiki_id TEXT,
                    page_type TEXT,
                    embedding BLOB,
                    updated_at TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection
