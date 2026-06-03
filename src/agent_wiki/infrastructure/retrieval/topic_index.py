from __future__ import annotations

import fcntl
import os
from pathlib import Path
import tempfile

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.infrastructure.retrieval.fuzzy import fuzzy_match
from agent_wiki.infrastructure.retrieval.tokenizer import tokenize

_HEADER = "| doc_id | page_type | topic | problem_cluster | summary |"
_DIVIDER = "| --- | --- | --- | --- | --- |"


class TopicIndexRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.path = wiki_root / "topic_index.md"
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("|") or line in {_HEADER, _DIVIDER}:
                continue
            parts = [part.strip() for part in line.strip("|").split("|")]
            if len(parts) != 5:
                continue
            rows.append({
                "doc_id": parts[0],
                "page_type": parts[1],
                "topic": parts[2],
                "problem_cluster": parts[3],
                "summary": parts[4],
            })
        return rows

    def upsert(self, row: dict) -> None:
        with self._exclusive_lock():
            rows = self.read_all()
            normalized = {
                "doc_id": str(row.get("doc_id", "")),
                "page_type": str(row.get("page_type", "")),
                "topic": str(row.get("topic", "")),
                "problem_cluster": str(row.get("problem_cluster", "")),
                "summary": str(row.get("summary", "")),
            }
            updated = False
            for index, existing in enumerate(rows):
                if existing["doc_id"] == normalized["doc_id"]:
                    rows[index] = normalized
                    updated = True
                    break
            if not updated:
                rows.append(normalized)
            self._write_all(rows)

    def find(self, doc_id: str) -> dict | None:
        for row in self.read_all():
            if row["doc_id"] == doc_id:
                return row
        return None

    def delete(self, doc_id: str) -> bool:
        with self._exclusive_lock():
            rows = self.read_all()
            remaining = [row for row in rows if row.get("doc_id") != doc_id]
            if len(remaining) == len(rows):
                return False
            self._write_all(remaining)
            return True

    def _write_all(self, rows: list[dict]) -> None:
        lines = [_HEADER, _DIVIDER]
        for row in rows:
            lines.append(
                f"| {self._sanitize(row['doc_id'])} | {self._sanitize(row['page_type'])} | {self._sanitize(row['topic'])} | {self._sanitize(row['problem_cluster'])} | {self._sanitize(row['summary'])} |"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temp = Path(temp_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            self._fsync_parent_dir()
        except Exception:
            temp.unlink(missing_ok=True)
            raise

    def _sanitize(self, value: str) -> str:
        return value.replace("|", "/")

    def _exclusive_lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return _FileLock(self.lock_path)

    def _fsync_parent_dir(self) -> None:
        try:
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


class StructuredIndexProvider:
    def __init__(self, wiki_root: Path, wiki_id: str) -> None:
        self.repository = TopicIndexRepository(wiki_root)
        self.wiki_id = wiki_id

    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]:
        terms = tokenize(query)
        lowercase_terms = [term.lower() for term in terms if term]
        required_terms = self._candidate_terms(lowercase_terms)
        page_types = self._filter_page_types(filters)
        hits: list[RetrievalHit] = []
        for row in self.repository.read_all():
            if page_types and row.get("page_type") not in page_types:
                continue
            searchable_text = " ".join(
                str(row.get(field, ""))
                for field in ("topic", "problem_cluster", "summary")
            ).lower()
            if required_terms and not self._might_match(searchable_text, required_terms):
                continue
            score = self._score_row(row, terms)
            if score <= 0:
                continue
            hits.append(RetrievalHit(wiki_id=self.wiki_id, doc_id=row["doc_id"], score=score, section="topic_index"))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def _filter_page_types(self, filters: dict | None) -> set[str]:
        if not filters:
            return set()
        if filters.get("page_types"):
            return {str(page_type) for page_type in filters["page_types"] if str(page_type)}
        if filters.get("page_type"):
            return {str(filters["page_type"])}
        return set()

    def _might_match(self, searchable_text: str, terms: list[str]) -> bool:
        for term in terms:
            if term in searchable_text:
                return True
            if len(term) >= 5 and term[:5] in searchable_text:
                return True
        return False

    def _candidate_terms(self, terms: list[str]) -> list[str]:
        strong = [term for term in terms if len(term) >= 4]
        return strong or terms

    def _score_row(self, row: dict, terms: list[str]) -> float:
        topic_tokens = tokenize(str(row.get("topic", "")))
        cluster_tokens = tokenize(str(row.get("problem_cluster", "")))
        summary_tokens = tokenize(str(row.get("summary", "")))
        topic_score = 0.0
        cluster_score = 0.0
        summary_score = 0.0
        for term in terms:
            if term in topic_tokens:
                topic_score += 3.0
                continue
            if term in cluster_tokens:
                cluster_score += 2.0
                continue
            if term in summary_tokens:
                summary_score += 1.5
                continue
            if any(fuzzy_match(token, term) for token in topic_tokens):
                topic_score += 1.5
                continue
            if any(fuzzy_match(token, term) for token in cluster_tokens):
                cluster_score += 1.0
                continue
            if any(fuzzy_match(token, term) for token in summary_tokens):
                summary_score += 0.5
        return min(topic_score, 3.0) + min(cluster_score, 2.0) + min(summary_score, 1.5)
