import json
from pathlib import Path

from pydantic import BaseModel, Field

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository


class FeedbackInput(BaseModel):
    query_id: str
    approved: bool
    missing_evidence: bool
    rewrite_targets: list[str] = Field(default_factory=list)
    notes: str = ""


class FeedbackResult(BaseModel):
    created_review_item: bool


class FeedbackService:
    def record(self, wiki: WikiConfig, data: FeedbackInput) -> FeedbackResult:
        wiki_root = Path(wiki.workspace_path)
        outcomes_path = wiki_root / "query_outcomes.jsonl"
        with outcomes_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data.model_dump(), ensure_ascii=False) + "\n")

        created_review_item = bool(data.missing_evidence or data.rewrite_targets)
        if created_review_item:
            ReviewQueueRepository(wiki_root).append(
                {
                    "item_type": "feedback_issue",
                    "wiki_id": wiki.wiki_id,
                    "doc_id": data.rewrite_targets[0] if data.rewrite_targets else data.query_id,
                    "reason": data.notes,
                    "content_state": {"query_id": data.query_id, "rewrite_targets": data.rewrite_targets},
                    "status": "open",
                }
            )
        return FeedbackResult(created_review_item=created_review_item)
