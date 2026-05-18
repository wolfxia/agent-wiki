import json
from datetime import UTC, datetime
from pathlib import Path

_VALID_TRANSITIONS = {
    "open": {"assigned", "failed"},
    "assigned": {"in_progress", "resolved", "failed"},
    "in_progress": {"resolved", "failed"},
    "resolved": {"archived"},
    "failed": {"archived"},
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

    def consume(self, item_type: str, actor_id: str, priority_filter: str | None = None) -> dict | None:
        items = self.read_all()
        candidates: list[tuple[int, dict]] = []
        for index, item in enumerate(items):
            if item.get("item_type") != item_type:
                continue
            if item.get("status", "open") != "open":
                continue
            if priority_filter and str(item.get("priority_label", "")).upper() != priority_filter.upper():
                continue
            candidates.append((index, item))
        if not candidates:
            return None

        index, item = sorted(candidates, key=lambda candidate: self._consume_sort_key(candidate[1]))[0]
        updated = {
            **item,
            "status": "assigned",
            "assigned_to": actor_id,
            "claimed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        items[index] = updated
        self._write_all(items)
        return updated

    def mark_resolved(self, item_id: str, content_state: dict | None = None) -> bool:
        return self._mark_terminal(item_id, "resolved", "resolved_at", content_state=content_state)

    def mark_failed(self, item_id: str, error: str) -> bool:
        return self._mark_terminal(item_id, "failed", "failed_at", extra={"last_error": error})

    def _mark_terminal(
        self,
        item_id: str,
        status: str,
        timestamp_field: str,
        content_state: dict | None = None,
        extra: dict | None = None,
    ) -> bool:
        items = self.read_all()
        for index, item in enumerate(items):
            if item.get("item_id") != item_id:
                continue
            current = item.get("content_state", {})
            updated = {
                **item,
                "status": status,
                timestamp_field: datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                **(extra or {}),
            }
            if content_state is not None:
                updated["content_state"] = {**current, **content_state}
            items[index] = updated
            self._write_all(items)
            return True
        return False

    def _consume_sort_key(self, item: dict) -> tuple[int, str, str]:
        try:
            priority = int(item.get("priority", 2))
        except (TypeError, ValueError):
            priority = 2
        return (priority, str(item.get("created_at", "")), str(item.get("item_id", "")))

    def remove_old_format_compile_suggestions(self) -> int:
        items = self.read_all()
        kept: list[dict] = []
        removed_count = 0
        for item in items:
            if item.get("item_type") == "compile_suggestion" and not self._is_current_compile_suggestion(item):
                removed_count += 1
                continue
            kept.append(item)
        if removed_count:
            self._write_all(kept)
        return removed_count

    def _is_current_compile_suggestion(self, item: dict) -> bool:
        return (
            bool(item.get("sub_cluster_id"))
            and isinstance(item.get("raw_doc_ids"), list)
            and isinstance(item.get("prepare_params"), dict)
        )

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
