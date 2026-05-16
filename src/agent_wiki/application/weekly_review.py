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

        queue_items: list[dict] = []
        if queue_path.exists():
            queue_items = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        outcomes: list[dict] = []
        if outcomes_path.exists():
            outcomes = [json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        manifest = ManifestRepository(wiki_root)
        entries = manifest.read_all()
        raw_count = sum(1 for e in entries if e.get("page_type") == "raw")

        purpose_reader = PurposeReader(wiki_root)
        purpose = purpose_reader.read()

        parts = []
        parts.append(f"{len(queue_items)} review_queue items, {len(outcomes)} feedback events")
        if raw_count:
            parts.append(f"{raw_count} raw pages in backlog")
        if purpose["topics"]:
            parts.append(f"purpose topics: {', '.join(purpose['topics'])}")
        if queue_items:
            parts.append(f"latest item_type={queue_items[-1].get('item_type', 'unknown')}")

        summary = "; ".join(parts)
        suggested_actions = [item.get("reason", "review queue follow-up") for item in queue_items if item.get("reason")]
        return WeeklyReviewReport(summary=summary, suggested_actions=suggested_actions)
