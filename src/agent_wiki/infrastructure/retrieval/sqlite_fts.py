from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from time import time

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.infrastructure.retrieval.tokenizer import JiebaTokenizer, Tokenizer


class SQLiteFTSIndexProvider:
    def __init__(self, wiki_root: Path, wiki_id: str, tokenizer: Tokenizer | None = None) -> None:
        self.wiki_root = wiki_root
        self.wiki_id = wiki_id
        self.db_path = wiki_root / ".agent-wiki" / "retrieval.db"
        self.tokenizer = tokenizer or JiebaTokenizer()

    def upsert(self, doc_id: str, payload: dict) -> None:
        self._ensure_schema()
        normalized = self._normalize_payload(doc_id, payload)
        with self._connect() as connection:
            connection.execute("DELETE FROM retrieval_fts WHERE doc_id = ?", (doc_id,))
            connection.execute(
                """
                INSERT INTO retrieval_fts(
                    doc_id, wiki_id, page_type, topic, problem_cluster, summary, content, tokens, sensitivity, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized["doc_id"],
                    normalized["wiki_id"],
                    normalized["page_type"],
                    normalized["topic"],
                    normalized["problem_cluster"],
                    normalized["summary"],
                    normalized["content"],
                    normalized["tokens"],
                    normalized["sensitivity"],
                    normalized["updated_at"],
                ),
            )

    def delete(self, doc_id: str) -> None:
        if not self.db_path.exists():
            return
        with self._connect() as connection:
            connection.execute("DELETE FROM retrieval_fts WHERE doc_id = ?", (doc_id,))

    def rebuild_from_manifest(self, manifest_entries: list[dict]) -> None:
        self._ensure_schema()
        with self._connect() as connection:
            connection.execute("DELETE FROM retrieval_fts")
        for entry in manifest_entries:
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                continue
            page_path = self.wiki_root / str(canonical_uri)
            if not page_path.exists() or not page_path.is_file():
                continue
            self.upsert(
                str(entry.get("doc_id", "")),
                {
                    **entry,
                    "content": page_path.read_text(encoding="utf-8"),
                },
            )

    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]:
        if not self.db_path.exists():
            return []
        match_query = self._match_query(query)
        if not match_query:
            return []
        params: list[object] = [match_query]
        where = "retrieval_fts MATCH ?"
        if filters and filters.get("page_type"):
            where += " AND page_type = ?"
            params.append(filters["page_type"])
        params.append(top_k)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT wiki_id, doc_id, bm25(retrieval_fts) AS rank
                    FROM retrieval_fts
                    WHERE {where}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            RetrievalHit(
                wiki_id=row["wiki_id"] or self.wiki_id,
                doc_id=row["doc_id"],
                score=max(0.0, -float(row["rank"])),
                section="fts5",
            )
            for row in rows
        ]

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS retrieval_fts USING fts5(
                    doc_id UNINDEXED,
                    wiki_id UNINDEXED,
                    page_type UNINDEXED,
                    topic,
                    problem_cluster,
                    summary,
                    content,
                    tokens,
                    sensitivity UNINDEXED,
                    updated_at UNINDEXED
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _normalize_payload(self, doc_id: str, payload: dict) -> dict:
        return {
            "doc_id": doc_id,
            "wiki_id": payload.get("wiki_id") or self.wiki_id,
            "page_type": payload.get("page_type") or "",
            "topic": payload.get("topic") or "",
            "problem_cluster": payload.get("problem_cluster") or "",
            "summary": payload.get("summary") or "",
            "content": payload.get("content") or "",
            "tokens": self._token_text(payload),
            "sensitivity": payload.get("sensitivity") or "",
            "updated_at": payload.get("updated_at") or str(time()),
        }

    def _match_query(self, query: str) -> str:
        terms = self.tokenizer.tokenize(query)
        if not terms:
            terms = [term for term in re.split(r"\s+", query.strip()) if term]
        sanitized = [term.replace('"', ' ') for term in terms]
        return " ".join(f'"{term.strip()}"' for term in sanitized if term.strip())

    def _token_text(self, payload: dict) -> str:
        source = " ".join(
            str(payload.get(field) or "")
            for field in ("topic", "problem_cluster", "summary", "content")
        )
        return " ".join(self.tokenizer.tokenize(source))
