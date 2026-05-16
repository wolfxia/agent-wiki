import json
from pathlib import Path


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
        return [json.loads(line) for line in self.stale_markers_path.read_text(encoding="utf-8").splitlines() if line.strip()]
