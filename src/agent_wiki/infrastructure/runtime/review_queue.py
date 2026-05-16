import json
from pathlib import Path


class ReviewQueueRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.path = wiki_root / "review_queue.jsonl"

    def append(self, entry: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
