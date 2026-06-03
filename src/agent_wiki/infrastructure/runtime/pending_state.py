import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class PendingStateRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.runtime_root = wiki_root / ".agent-wiki"
        self.runtime_root.mkdir(exist_ok=True)
        self.pending_manifest_path = self.runtime_root / "pending_manifest.jsonl"
        self.stale_markers_path = self.runtime_root / "stale_markers.jsonl"

    def append_pending_manifest(self, entry: dict) -> None:
        with self.pending_manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def append_stale_marker(self, entry: dict) -> None:
        with self.stale_markers_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_stale_markers(self) -> list[dict]:
        if not self.stale_markers_path.exists():
            return []
        return self._read_jsonl(self.stale_markers_path)

    def read_pending_manifest(self) -> list[dict]:
        if not self.pending_manifest_path.exists():
            return []
        return self._read_jsonl(self.pending_manifest_path)

    def _read_jsonl(self, path: Path) -> list[dict]:
        entries: list[dict] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as error:
                logger.warning("Skipping corrupt pending state line %s in %s: %s", line_number, path, error)
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries
