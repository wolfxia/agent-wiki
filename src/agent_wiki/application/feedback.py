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
    accepted_doc_ids: list[str] = Field(default_factory=list)
    rejected_doc_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class FeedbackResult(BaseModel):
    created_review_item: bool


class FeedbackService:
    def record(self, wiki: WikiConfig, data: FeedbackInput) -> FeedbackResult:
        wiki_root = Path(wiki.workspace_path)
        outcomes_path = wiki_root / "query_outcomes.jsonl"
        self._update_query_labels(outcomes_path, data)
        with outcomes_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data.model_dump(), ensure_ascii=False) + "\n")

        created_review_item = bool((not data.approved) or data.missing_evidence or data.rewrite_targets)
        if created_review_item:
            ReviewQueueRepository(wiki_root).append(
                {
                    "item_type": "feedback_issue",
                    "item_id": f"feedback_issue:{data.query_id}",
                    "wiki_id": wiki.wiki_id,
                    "doc_id": data.rewrite_targets[0] if data.rewrite_targets else data.query_id,
                    "reason": data.notes,
                    "content_state": {
                        "query_id": data.query_id,
                        "rewrite_targets": data.rewrite_targets,
                        "accepted_doc_ids": data.accepted_doc_ids,
                        "rejected_doc_ids": data.rejected_doc_ids,
                    },
                    "status": "open",
                }
            )
        return FeedbackResult(created_review_item=created_review_item)

    def _update_query_labels(self, outcomes_path: Path, data: FeedbackInput) -> None:
        if not outcomes_path.exists():
            return
        updated = False
        entries: list[dict] = []
        for line in outcomes_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("query_id") == data.query_id and "query" in entry:
                entry["accepted_doc_ids"] = data.accepted_doc_ids
                entry["rejected_doc_ids"] = data.rejected_doc_ids
                updated = True
            entries.append(entry)
        if not updated:
            return
        outcomes_path.write_text(
            "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
            encoding="utf-8",
        )
