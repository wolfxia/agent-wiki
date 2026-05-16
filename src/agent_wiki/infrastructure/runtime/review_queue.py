import json
from datetime import UTC, datetime
from pathlib import Path

_VALID_TRANSITIONS = {
    "open": {"assigned"},
    "assigned": {"in_progress"},
    "in_progress": {"resolved"},
    "resolved": {"archived"},
}


class ReviewQueueRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.path = wiki_root / "review_queue.jsonl"

    def append(self, entry: dict) -> None:
        normalized = self._normalize_entry(entry)
        item_id = normalized.get("item_id")
        if item_id and self.find(item_id) is not None:
            return
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def find(self, item_id: str) -> dict | None:
        for item in self.read_all():
            if item.get("item_id") == item_id:
                return item
        return None

    def transition(self, item_id: str, new_status: str) -> bool:
        items = self.read_all()
        for i, item in enumerate(items):
            if item.get("item_id") == item_id:
                current = item.get("status", "open")
                allowed = _VALID_TRANSITIONS.get(current, set())
                if new_status not in allowed:
                    return False
                items[i] = {**item, "status": new_status}
                self._write_all(items)
                return True
        return False

    def _normalize_entry(self, entry: dict) -> dict:
        item_type = entry.get("item_type", "task")
        doc_id = entry.get("doc_id", "unknown")
        normalized = dict(entry)
        normalized.setdefault("item_id", f"{item_type}:{doc_id}")
        normalized.setdefault("wiki_id", self.path.parent.name if self.path.parent.name else "unknown")
        normalized.setdefault("status", "open")
        normalized.setdefault("priority", 2)
        normalized.setdefault("created_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        normalized.setdefault("content_state", {})
        return normalized

    def _write_all(self, items: list[dict]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
