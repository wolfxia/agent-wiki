import fcntl
import json
import logging
import os
from pathlib import Path
import tempfile


logger = logging.getLogger(__name__)


class ManifestRepository:
    """
    Repository for MANIFEST.jsonl.

    Uses fcntl.flock for cross-process mutual exclusion on all write operations.
    This prevents data corruption when multiple aw-agent serve instances
    (OpenClaw + Hermes) share the same wiki workspace.
    """

    def __init__(self, wiki_root: Path) -> None:
        self.wiki_root = wiki_root
        self.manifest_path = wiki_root / "MANIFEST.jsonl"
        self._cache_stat: tuple[int, int] | None = None
        self._cache_entries: list[dict] | None = None
        self._lock_fd: int | None = None

    def _ensure_lock_fd(self) -> int:
        if self._lock_fd is None:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            self._lock_fd = os.open(
                str(self.manifest_path),
                os.O_RDONLY | os.O_CREAT,
                0o644,
            )
        return self._lock_fd

    def _acquire_exclusive(self) -> None:
        """Acquire exclusive (write) lock on MANIFEST.jsonl across processes."""
        fcntl.flock(self._ensure_lock_fd(), fcntl.LOCK_EX)

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass

    def append(self, entry: dict) -> None:
        self._acquire_exclusive()
        try:
            entries = self.read_all()
            if any(existing["doc_id"] == entry["doc_id"] for existing in entries):
                raise ValueError(f"duplicate doc_id: {entry['doc_id']}")
            entries.append(entry)
            self._write_all(entries)
        finally:
            self._release_lock()

    def upsert(self, entry: dict) -> None:
        self.batch_upsert([entry])

    def batch_upsert(self, new_entries: list[dict]) -> None:
        if not new_entries:
            return
        self._acquire_exclusive()
        try:
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
        finally:
            self._release_lock()

    def _write_all(self, entries: list[dict]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{self.manifest_path.name}.",
            suffix=".tmp",
            dir=self.manifest_path.parent,
        )
        temp = Path(temp_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for item in entries:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.manifest_path)
            self._fsync_parent_dir()
            self._cache_stat = None
            self._cache_entries = None
        except Exception:
            temp.unlink(missing_ok=True)
            raise

    def _fsync_parent_dir(self) -> None:
        try:
            dir_fd = os.open(self.manifest_path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def read_all(self) -> list[dict]:
        if not self.manifest_path.exists():
            return []
        stat = self.manifest_path.stat()
        cache_stat = (stat.st_mtime_ns, stat.st_size)
        if self._cache_stat == cache_stat and self._cache_entries is not None:
            return [dict(entry) for entry in self._cache_entries]

        entries: list[dict] = []
        with self.manifest_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as error:
                    logger.warning(
                        "Skipping corrupt manifest line %s in %s: %s",
                        line_number,
                        self.manifest_path,
                        error,
                    )
                    continue
                if not isinstance(entry, dict):
                    logger.warning(
                        "Skipping non-object manifest line %s in %s",
                        line_number,
                        self.manifest_path,
                    )
                    continue
                entries.append(entry)
        self._cache_stat = cache_stat
        self._cache_entries = [dict(entry) for entry in entries]
        return entries

    def find(self, doc_id: str) -> dict | None:
        for entry in self.read_all():
            if entry["doc_id"] == doc_id:
                return entry
        return None

    def delete(self, doc_id: str) -> bool:
        self._acquire_exclusive()
        try:
            entries = self.read_all()
            remaining = [entry for entry in entries if entry.get("doc_id") != doc_id]
            if len(remaining) == len(entries):
                return False
            self._write_all(remaining)
            return True
        finally:
            self._release_lock()
