from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from agent_wiki.infrastructure.doc_id import doc_id_from_relative_path
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository


class MigrationResult(BaseModel):
    changed_count: int
    backup_path: str | None = None


class SlugifyDocIdsMigration:
    def run(self, wiki_root: Path) -> MigrationResult:
        manifest_path = wiki_root / "MANIFEST.jsonl"
        if not manifest_path.exists():
            return MigrationResult(changed_count=0)

        backup_path = wiki_root / "MANIFEST.jsonl.pre-migration"
        if not backup_path.exists():
            shutil.copyfile(manifest_path, backup_path)

        entries = self._read_jsonl(manifest_path)
        mapping: dict[str, str] = {}
        changed_count = 0
        for entry in entries:
            vault_relative_path = entry.get("vault_relative_path")
            if not vault_relative_path:
                continue
            new_doc_id = doc_id_from_relative_path(vault_relative_path)
            old_doc_id = entry.get("doc_id")
            if not old_doc_id or old_doc_id == new_doc_id:
                continue
            mapping[old_doc_id] = new_doc_id
            entry["doc_id"] = new_doc_id
            entry["canonical_uri"] = f"pages/{new_doc_id}.md"
            self._rename_page(wiki_root, old_doc_id, new_doc_id)
            changed_count += 1

        if mapping:
            self._rewrite_source_refs(entries, mapping)
            self._write_jsonl(manifest_path, entries)
            self._rewrite_retrieval_index(wiki_root, mapping)
            self._rewrite_topic_index(wiki_root, mapping)

        return MigrationResult(changed_count=changed_count, backup_path=str(backup_path))

    def _read_jsonl(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _write_jsonl(self, path: Path, entries: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _rename_page(self, wiki_root: Path, old_doc_id: str, new_doc_id: str) -> None:
        old_path = wiki_root / "pages" / f"{old_doc_id}.md"
        new_path = wiki_root / "pages" / f"{new_doc_id}.md"
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)

    def _rewrite_source_refs(self, entries: list[dict], mapping: dict[str, str]) -> None:
        for entry in entries:
            refs = entry.get("source_refs")
            if not isinstance(refs, list):
                continue
            rewritten = []
            for ref in refs:
                wiki_id, sep, doc_id = str(ref).partition(":")
                if sep and doc_id in mapping:
                    rewritten.append(f"{wiki_id}:{mapping[doc_id]}")
                else:
                    rewritten.append(ref)
            entry["source_refs"] = rewritten

    def _rewrite_retrieval_index(self, wiki_root: Path, mapping: dict[str, str]) -> None:
        path = wiki_root / "retrieval_index.jsonl"
        if not path.exists():
            return
        entries = self._read_jsonl(path)
        for entry in entries:
            doc_id = entry.get("doc_id")
            if doc_id in mapping:
                entry["doc_id"] = mapping[doc_id]
        self._write_jsonl(path, entries)

    def _rewrite_topic_index(self, wiki_root: Path, mapping: dict[str, str]) -> None:
        repository = TopicIndexRepository(wiki_root)
        rows = repository.read_all()
        if not rows:
            return
        for row in rows:
            doc_id = row.get("doc_id")
            if doc_id in mapping:
                row["doc_id"] = mapping[doc_id]
        repository._write_all(rows)
