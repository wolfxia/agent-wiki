import json
from pathlib import Path

from pydantic import BaseModel, Field

from agent_wiki.bootstrap.registry_loader import WikiConfig


class WeeklyReviewReport(BaseModel):
    summary: str
    suggested_actions: list[str] = Field(default_factory=list)


class WeeklyReviewService:
    def generate(self, wiki: WikiConfig) -> WeeklyReviewReport:
        wiki_root = Path(wiki.workspace_path)
        queue_path = wiki_root / "review_queue.jsonl"
        outcomes_path = wiki_root / "query_outcomes.jsonl"

        queue_items: list[dict] = []
        if queue_path.exists():
            queue_items = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        outcomes: list[dict] = []
        if outcomes_path.exists():
            outcomes = [json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        summary = f"{len(queue_items)} review_queue items, {len(outcomes)} feedback events"
        if queue_items:
            summary += f"; latest item_type={queue_items[-1].get('item_type', 'unknown')}"

        suggested_actions = [item.get("reason", "review queue follow-up") for item in queue_items if item.get("reason")]
        return WeeklyReviewReport(summary=summary, suggested_actions=suggested_actions)
