import json
from pathlib import Path

from agent_wiki.application.feedback import FeedbackInput, FeedbackService
from agent_wiki.bootstrap.registry_loader import RegistryLoader


def test_feedback_creates_review_queue_item(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    service = FeedbackService()

    result = service.record(
        wiki,
        FeedbackInput(
            query_id="q-1",
            approved=False,
            missing_evidence=True,
            rewrite_targets=["atom-a"],
            notes="needs stronger proof",
        ),
    )

    assert result.created_review_item is True
    queue_item = json.loads((temp_wiki_root / "review_queue.jsonl").read_text().strip())
    assert queue_item["item_type"] == "feedback_issue"
    assert queue_item["reason"] == "needs stronger proof"
