from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path
from time import time

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.infrastructure.retrieval.tokenizer import JiebaTokenizer, Tokenizer

_CJK_TOKEN = re.compile(r"[㐀-䶿一-鿿]+")


class SQLiteFTSIndexProvider:
    def __init__(self, wiki_root: Path, wiki_id: str, tokenizer: Tokenizer | None = None) -> None:
        self.wiki_root = wiki_root
        self.wiki_id = wiki_id
        self.db_path = wiki_root / ".agent-wiki" / "retrieval.db"
        self.tokenizer = tokenizer or JiebaTokenizer()

    def upsert(self, doc_id: str, payload: dict) -> None:
        self.batch_upsert([(doc_id, payload)])

    def batch_upsert(self, items: list[tuple[str, dict]]) -> None:
        if not items:
            return
        self._ensure_schema()
        normalized_items = [self._normalize_payload(doc_id, payload) for doc_id, payload in items]
        self._write_normalized(normalized_items)

    def _write_normalized(self, normalized_items: list[dict]) -> None:
        if not normalized_items:
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "DELETE FROM retrieval_fts WHERE doc_id = ?",
                [(item["doc_id"],) for item in normalized_items],
            )
            connection.executemany(
                """
                INSERT INTO retrieval_fts(
                    doc_id, wiki_id, page_type, topic, problem_cluster, summary, content, tokens, sensitivity, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
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
                    )
                    for normalized in normalized_items
                ],
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
        upserts: list[tuple[str, dict]] = []
        for entry in manifest_entries:
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                continue
            page_path = self.wiki_root / str(canonical_uri)
            if not page_path.exists() or not page_path.is_file():
                continue
            upserts.append(
                (
                    str(entry.get("doc_id", "")),
                    {
                    **entry,
                    "content": page_path.read_text(encoding="utf-8"),
                    },
                )
            )
        self._write_normalized([self._normalize_payload(doc_id, payload) for doc_id, payload in upserts])

    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]:
        if not self.db_path.exists():
            return []
        match_queries = self._match_queries(query)
        if not match_queries:
            return []
        rows = []
        for match_query in match_queries:
            params: list[object] = [match_query]
            where = "retrieval_fts MATCH ?"
            page_types = self._filter_page_types(filters)
            if page_types:
                placeholders = ",".join("?" for _ in page_types)
                where += f" AND page_type IN ({placeholders})"
                params.extend(page_types)
            params.append(top_k)
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        f"""
                        SELECT wiki_id, doc_id, page_type, problem_cluster, bm25(retrieval_fts, 0.0, 0.0, 0.0, 8.0, 6.0, 5.0, 1.0, 3.0, 0.0, 0.0) AS rank
                        FROM retrieval_fts
                        WHERE {where}
                        ORDER BY rank
                        LIMIT ?
                        """,
                        params,
                    ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if rows:
                break
        return [
            RetrievalHit(
                wiki_id=row["wiki_id"] or self.wiki_id,
                doc_id=row["doc_id"],
                score=self._score_from_rank(float(row["rank"])),
                section="fts5",
                metadata={
                    "fts_rank": float(row["rank"]),
                    "page_type": row["page_type"] or "",
                    "problem_cluster": row["problem_cluster"] or "",
                },
            )
            for row in rows
        ]

    def _score_from_rank(self, rank: float) -> float:
        strength = max(-rank, 0.0)
        if not strength:
            return 0.0
        reference_rank = 1.0
        scaled = 4.0 * math.log10(1.0 + (strength / reference_rank))
        return min(scaled, 20.0)

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

    def _match_queries(self, query: str) -> list[str]:
        terms = self.tokenizer.tokenize(query)
        if not terms:
            terms = [term for term in re.split(r"\s+", query.strip()) if term]
        sanitized = [self._sanitize_term(term) for term in terms]
        sanitized = [term for term in sanitized if term]
        sanitized = list(dict.fromkeys(sanitized))
        if not sanitized:
            return []
        exact = " ".join(f'"{term}"' for term in sanitized)
        prefix = " OR ".join(f"{term}*" for term in sanitized if len(term) >= 3)
        if len(sanitized) <= 2:
            return [exact, prefix] if prefix and prefix != exact else [exact]
        phrase = self._sanitize_phrase(query)
        phrase_match = f'"{phrase}"' if phrase else exact
        token_mix = " OR ".join(f'"{term}"' for term in sanitized)
        queries: list[str] = []
        anchor = self._anchor_query(sanitized)
        if anchor:
            queries.append(anchor)
        token_and = " AND ".join(f'"{term}"' for term in sanitized)
        if token_and not in queries:
            queries.append(token_and)
        if phrase_match and phrase_match not in queries:
            queries.append(phrase_match)
        broad = f"{phrase_match} OR ({token_mix})" if phrase_match else token_mix
        if broad and broad not in queries:
            queries.append(broad)
        return queries

    def _anchor_query(self, sanitized_terms: list[str]) -> str | None:
        latin_terms = [
            term
            for term in sanitized_terms
            if re.fullmatch(r"[a-z0-9-]+", term) and not term.isdigit()
        ]
        cjk_terms = [term for term in sanitized_terms if _CJK_TOKEN.fullmatch(term)]

        latin_anchors = [term for term in latin_terms if len(term) >= 4][:3]
        cjk_anchors = [term for term in cjk_terms if len(term) >= 2][:2]

        clauses: list[str] = [f'"{term}"' for term in latin_anchors]
        if cjk_anchors:
            if len(cjk_anchors) == 1:
                clauses.append(f'"{cjk_anchors[0]}"')
            else:
                clauses.append("(" + " OR ".join(f'"{term}"' for term in cjk_anchors) + ")")

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return " AND ".join(clauses)

    def _sanitize_term(self, term: str) -> str:
        return re.sub(r'[^\w\u4e00-\u9fff-]+', ' ', term.replace('"', ' ')).strip()

    def _sanitize_phrase(self, query: str) -> str:
        return re.sub(r'\s+', ' ', query.replace('"', ' ')).strip()

    def _filter_page_types(self, filters: dict | None) -> list[str]:
        if not filters:
            return []
        if filters.get("page_types"):
            return [str(page_type) for page_type in filters["page_types"] if str(page_type)]
        if filters.get("page_type"):
            return [str(filters["page_type"])]
        return []

    def _token_text(self, payload: dict) -> str:
        source = " ".join(
            str(payload.get(field) or "")
            for field in ("topic", "problem_cluster", "summary", "content")
        )
        aliases = " ".join(str(alias) for alias in (payload.get("aliases") or []))
        return " ".join(self.tokenizer.tokenize(f"{source} {aliases}".strip()))
