import json
from pathlib import Path


class ManifestRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.wiki_root = wiki_root
        self.manifest_path = wiki_root / "MANIFEST.jsonl"

    def append(self, entry: dict) -> None:
        entries = self.read_all()
        if any(existing["doc_id"] == entry["doc_id"] for existing in entries):
            raise ValueError(f"duplicate doc_id: {entry['doc_id']}")
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def upsert(self, entry: dict) -> None:
        self.batch_upsert([entry])

    def batch_upsert(self, new_entries: list[dict]) -> None:
        if not new_entries:
            return
        entries = self.read_all()
        entry_indexes = {entry["doc_id"]: index for index, entry in enumerate(entries)}
        for entry in new_entries:
            existing_index = entry_indexes.get(entry["doc_id"])
            if existing_index is None:
                entry_indexes[entry["doc_id"]] = len(entries)
                entries.append(entry)
                continue
            entries[existing_index] = {**entries[existing_index], **entry}
        self._write_all(entries)

    def _write_all(self, entries: list[dict]) -> None:
        with self.manifest_path.open("w", encoding="utf-8") as handle:
            for item in entries:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        if not self.manifest_path.exists():
            return []
        return [json.loads(line) for line in self.manifest_path.read_text().splitlines() if line.strip()]

    def find(self, doc_id: str) -> dict | None:
        for entry in self.read_all():
            if entry["doc_id"] == doc_id:
                return entry
        return None

    def delete(self, doc_id: str) -> bool:
        entries = self.read_all()
        remaining = [entry for entry in entries if entry.get("doc_id") != doc_id]
        if len(remaining) == len(entries):
            return False
        self._write_all(remaining)
        return True
