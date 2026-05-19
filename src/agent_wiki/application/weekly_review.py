import json
from pathlib import Path

from pydantic import BaseModel, Field

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository
from agent_wiki.infrastructure.storage.purpose_reader import PurposeReader


class WeeklyReviewReport(BaseModel):
    summary: str
    suggested_actions: list[str] = Field(default_factory=list)


class WeeklyReviewService:
    def generate(self, wiki: WikiConfig) -> WeeklyReviewReport:
        wiki_root = Path(wiki.workspace_path)
        queue_path = wiki_root / "review_queue.jsonl"
        outcomes_path = wiki_root / "query_outcomes.jsonl"
        feedback_path = wiki_root / "feedback_outcomes.jsonl"

        queue_items: list[dict] = []
        if queue_path.exists():
            queue_items = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        active_queue_items = [item for item in queue_items if item.get("status", "open") in {"open", "assigned", "in_progress"}]

        outcomes: list[dict] = []
        if outcomes_path.exists():
            outcomes = [json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        feedback_events: list[dict] = []
        if feedback_path.exists():
            feedback_events = [json.loads(line) for line in feedback_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        query_events = [entry for entry in outcomes if "query" in entry and "hit_count" in entry]
        miss_signals = sum(1 for entry in query_events if entry.get("hit_count", 0) == 0)

        manifest = ManifestRepository(wiki_root)
        entries = manifest.read_all()
        raw_count = sum(1 for e in entries if e.get("page_type") == "raw")

        purpose_reader = PurposeReader(wiki_root)
        purpose = purpose_reader.read()

        parts = []
        parts.append(f"{len(active_queue_items)} active review_queue items, {len(feedback_events)} feedback events")
        if miss_signals:
            parts.append(f"{miss_signals} miss signals")
        if raw_count:
            parts.append(f"{raw_count} raw pages in backlog")
        if purpose["topics"]:
            parts.append(f"purpose topics: {', '.join(purpose['topics'])}")

        # Summarize queue item types
        type_counts: dict[str, int] = {}
        for item in active_queue_items:
            item_type = item.get("item_type", "unknown")
            type_counts[item_type] = type_counts.get(item_type, 0) + 1
        for item_type, count in sorted(type_counts.items()):
            parts.append(f"{count} {item_type}")

        summary = "; ".join(parts)
        suggested_actions = [item.get("reason", "review queue follow-up") for item in active_queue_items if item.get("reason")]
        suggested_actions.extend(entry.get("notes") for entry in feedback_events if entry.get("notes"))
        return WeeklyReviewReport(summary=summary, suggested_actions=suggested_actions)
