import json
from pathlib import Path


class PendingStateRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.runtime_root = wiki_root / ".agent-wiki"
        self.runtime_root.mkdir(exist_ok=True)
        self.pending_manifest_path = self.runtime_root / "pending_manifest.jsonl"

    def append_pending_manifest(self, entry: dict) -> None:
        with self.pending_manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
