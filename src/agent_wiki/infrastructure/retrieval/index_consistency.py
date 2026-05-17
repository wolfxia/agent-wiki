from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class IndexConsistencyChecker:
    def check(self, wiki_root: Path) -> list[str]:
        manifest_doc_ids = {
            entry.get("doc_id")
            for entry in ManifestRepository(wiki_root).read_all()
            if entry.get("doc_id")
        }
        issues: list[str] = []

        retrieval_doc_ids = self._read_retrieval_index_doc_ids(wiki_root)
        for doc_id in sorted(manifest_doc_ids - retrieval_doc_ids):
            issues.append(f"retrieval index missing manifest entry: {doc_id}")
        for doc_id in sorted(retrieval_doc_ids - manifest_doc_ids):
            issues.append(f"retrieval index entry without manifest entry: {doc_id}")

        fts_doc_ids = self._read_fts_doc_ids(wiki_root)
        for doc_id in sorted(manifest_doc_ids - fts_doc_ids):
            issues.append(f"fts index missing manifest entry: {doc_id}")
        for doc_id in sorted(fts_doc_ids - manifest_doc_ids):
            issues.append(f"fts index entry without manifest entry: {doc_id}")

        if issues:
            issues.append("rebuild retrieval indexes with aw sync pull-view or maintenance")
        return issues

    def _read_retrieval_index_doc_ids(self, wiki_root: Path) -> set[str]:
        path = wiki_root / "retrieval_index.jsonl"
        if not path.exists():
            return set()
        doc_ids: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            card = json.loads(line)
            doc_id = card.get("doc_id")
            if doc_id:
                doc_ids.add(str(doc_id))
        return doc_ids

    def _read_fts_doc_ids(self, wiki_root: Path) -> set[str]:
        path = wiki_root / ".agent-wiki" / "retrieval.db"
        if not path.exists():
            return set()
        try:
            with sqlite3.connect(path) as connection:
                rows = connection.execute("SELECT doc_id FROM retrieval_fts").fetchall()
        except sqlite3.Error:
            return set()
        return {str(row[0]) for row in rows if row and row[0]}
