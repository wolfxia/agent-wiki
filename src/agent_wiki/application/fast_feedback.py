import json
from collections import defaultdict
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository

ZERO_HIT_THRESHOLD = 3


class FastFeedbackService:
    def detect_low_value_queries(self, wiki: WikiConfig, threshold: int = ZERO_HIT_THRESHOLD) -> list[dict]:
        wiki_root = Path(wiki.workspace_path)
        outcomes_path = wiki_root / "query_outcomes.jsonl"
        if not outcomes_path.exists():
            return []

        zero_hit_counts: dict[str, int] = defaultdict(int)
        for line in outcomes_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("hit_count", 0) == 0:
                zero_hit_counts[entry["query"]] += 1

        signals = []
        for query, count in zero_hit_counts.items():
            if count >= threshold:
                signals.append({
                    "query": query,
                    "zero_hit_count": count,
                })

        signals.sort(key=lambda s: s["zero_hit_count"], reverse=True)
        return signals

    def detect_and_enqueue(self, wiki: WikiConfig, threshold: int = ZERO_HIT_THRESHOLD) -> list[dict]:
        signals = self.detect_low_value_queries(wiki, threshold)
        if not signals:
            return signals

        wiki_root = Path(wiki.workspace_path)
        queue = ReviewQueueRepository(wiki_root)
        for signal in signals:
            queue.append({
                "item_id": f"quality_signal:{signal['query']}",
                "item_type": "quality_signal",
                "query": signal["query"],
                "zero_hit_count": signal["zero_hit_count"],
                "status": "open",
            })
        return signals
