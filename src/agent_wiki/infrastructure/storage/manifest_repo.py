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
        entries = self.read_all()
        updated = False
        for index, existing in enumerate(entries):
            if existing["doc_id"] == entry["doc_id"]:
                entries[index] = {**existing, **entry}
                updated = True
                break
        if not updated:
            entries.append(entry)
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
        with self.manifest_path.open("w", encoding="utf-8") as handle:
            for item in remaining:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        return True
