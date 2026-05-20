import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

_VALID_TRANSITIONS = {
    "open": {"assigned", "failed"},
    "assigned": {"in_progress", "resolved", "failed"},
    "in_progress": {"resolved", "failed"},
    "resolved": {"archived"},
    "failed": {"archived"},
}

_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())


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

    def append_many(self, entries: list[dict]) -> int:
        if not entries:
            return 0
        items = self.read_all()
        existing_ids = {item.get("item_id") for item in items if item.get("item_id")}
        appended = 0
        for entry in entries:
            normalized = self._normalize_entry(entry)
            item_id = normalized.get("item_id")
            if item_id and item_id in existing_ids:
                continue
            items.append(normalized)
            if item_id:
                existing_ids.add(item_id)
            appended += 1
        if appended:
            self._write_all(items)
        return appended

    def upsert_compile_suggestions(self, entries: list[dict]) -> int:
        if not entries:
            return 0
        items = self.read_all()
        item_indexes = {item.get("item_id"): index for index, item in enumerate(items) if item.get("item_id")}
        changed = 0
        for entry in entries:
            normalized = self._normalize_entry(entry)
            item_id = normalized.get("item_id")
            if not item_id:
                continue
            existing_index = item_indexes.get(item_id)
            if existing_index is None:
                item_indexes[item_id] = len(items)
                items.append(normalized)
                changed += 1
                continue

            existing = items[existing_index]
            if not self._should_update_compile_suggestion(existing, normalized):
                continue
            created_at = existing.get("created_at", normalized.get("created_at"))
            items[existing_index] = {**existing, **normalized, "created_at": created_at}
            changed += 1
        if changed:
            self._write_all(items)
        return changed

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


    def recover_assigned_timeouts(self, now: str | datetime | None = None, timeout_minutes: int = 30) -> int:
        now_dt = self._parse_timestamp(now) if now is not None else datetime.now(UTC)
        cutoff = now_dt - timedelta(minutes=timeout_minutes)
        items = self.read_all()
        recovered_count = 0
        recovered_at = self._format_timestamp(now_dt)
        for index, item in enumerate(items):
            if item.get("status") != "assigned":
                continue
            claimed_at = self._parse_timestamp(item.get("claimed_at"))
            if claimed_at is None or claimed_at > cutoff:
                continue
            updated = dict(item)
            assigned_to = updated.pop("assigned_to", None)
            updated.pop("claimed_at", None)
            updated["status"] = "open"
            updated["timeout_recovered_at"] = recovered_at
            if assigned_to is not None:
                updated["previous_assigned_to"] = assigned_to
            items[index] = updated
            recovered_count += 1
        if recovered_count:
            self._write_all(items)
        return recovered_count

    def _parse_timestamp(self, value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _format_timestamp(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def mark_resolved(self, item_id: str, content_state: dict | None = None) -> bool:
        return self._mark_terminal(item_id, "resolved", "resolved_at", content_state=content_state)

    def mark_failed(self, item_id: str, error: str, content_state: dict | None = None) -> bool:
        return self._mark_terminal(
            item_id,
            "failed",
            "failed_at",
            content_state=content_state,
            extra={"last_error": error},
        )

    def release_assignment(self, item_id: str) -> bool:
        items = self.read_all()
        for index, item in enumerate(items):
            if item.get("item_id") != item_id:
                continue
            updated = dict(item)
            assigned_to = updated.pop("assigned_to", None)
            updated.pop("claimed_at", None)
            if assigned_to is not None:
                updated["previous_assigned_to"] = assigned_to
            items[index] = updated
            self._write_all(items)
            return True
        return False

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

    def _should_update_compile_suggestion(self, existing: dict, candidate: dict) -> bool:
        if existing.get("item_type") != "compile_suggestion" or candidate.get("item_type") != "compile_suggestion":
            return False
        if existing.get("status") in {"assigned", "in_progress"}:
            return False
        return self._compile_suggestion_fingerprint(existing) != self._compile_suggestion_fingerprint(candidate)

    def _compile_suggestion_fingerprint(self, item: dict) -> tuple:
        return (
            tuple(str(doc_id) for doc_id in item.get("raw_doc_ids") or []),
            item.get("raw_count"),
            item.get("cluster_raw_count"),
            item.get("sub_cluster_index"),
            item.get("sub_cluster_id"),
        )

    def _normalize_entry(self, entry: dict) -> dict:
        item_type = entry.get("item_type", "task")
        doc_id = entry.get("doc_id", "unknown")
        normalized = dict(entry)
        normalized.setdefault("item_id", f"{item_type}:{doc_id}")
        normalized.setdefault("wiki_id", self.path.parent.name if self.path.parent.name else "unknown")
        normalized.setdefault("status", "open")
        status = str(normalized.get("status", "open")).strip().lower()
        if status not in _VALID_STATUSES:
            status = "open"
        normalized["status"] = status
        normalized.setdefault("priority", 2)
        normalized.setdefault("created_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        normalized.setdefault("content_state", {})
        return normalized

    def _write_all(self, items: list[dict]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
