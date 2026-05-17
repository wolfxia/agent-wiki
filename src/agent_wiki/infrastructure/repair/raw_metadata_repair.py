from __future__ import annotations

import json
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.intake.raw_intake import normalize_raw_intake
from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class RawMetadataRepairService:
    def repair(self, wiki: WikiConfig) -> dict:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        pending = PendingStateRepository(wiki_root)
        pages_root = wiki_root / "pages"
        repaired_count = 0
        unresolved: list[str] = []

        pending_entries = self._read_pending_entries(pending.pending_manifest_path)
        kept_entries: list[dict] = []
        for entry in pending_entries:
            if entry.get("page_type") != "raw":
                kept_entries.append(entry)
                continue
            doc_id = entry.get("doc_id")
            if not doc_id:
                kept_entries.append(entry)
                continue
            page_path = pages_root / f"{doc_id}.md"
            if not page_path.exists():
                unresolved.append(doc_id)
                kept_entries.append(entry)
                continue

            intake = normalize_raw_intake(
                {
                    "doc_id": doc_id,
                    "content": page_path.read_text(encoding="utf-8"),
                    "topic": entry.get("topic"),
                    "problem_cluster": entry.get("problem_cluster"),
                    "summary": entry.get("summary"),
                    "classification_confidence": entry.get("classification_confidence"),
                    "source_type": entry.get("source") or "external_sync",
                    "source_uri": entry.get("vault_relative_path") or f"pages/{doc_id}.md",
                    "adapter_metadata": entry.get("adapter_metadata") or {},
                }
            )

            manifest.upsert(
                {
                    "wiki_id": wiki.wiki_id,
                    "doc_id": doc_id,
                    "page_type": "raw",
                    "topic": intake["topic"],
                    "problem_cluster": intake["problem_cluster"],
                    "summary": intake["summary"],
                    "classification_method": intake["classification_method"],
                    "classification_confidence": intake["classification_confidence"],
                    "metadata_state": intake["metadata_state"],
                    "source_type": intake["source_type"],
                    "source_uri": intake["source_uri"],
                    "title": intake["title"],
                    "canonical_uri": f"pages/{doc_id}.md",
                    "last_writer": entry.get("last_writer", "repair"),
                    "vault_relative_path": entry.get("vault_relative_path"),
                    "adapter_metadata": intake["adapter_metadata"],
                }
            )
            repaired_count += 1

        self._write_pending_entries(pending.pending_manifest_path, kept_entries)
        return {
            "repaired_count": repaired_count,
            "unresolved": unresolved,
            "metadata_repair_candidates": repaired_count + len(unresolved),
        }

    def _read_pending_entries(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _write_pending_entries(self, path: Path, entries: list[dict]) -> None:
        if not entries:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
