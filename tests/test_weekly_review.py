from pathlib import Path

from agent_wiki.application.feedback import FeedbackInput, FeedbackService
from agent_wiki.application.weekly_review import WeeklyReviewService
from agent_wiki.bootstrap.registry_loader import RegistryLoader


def test_weekly_review_summarizes_feedback_and_queue(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    feedback_service = FeedbackService()
    weekly_review_service = WeeklyReviewService()

    feedback_service.record(
        wiki,
        FeedbackInput(
            query_id="q-2",
            approved=False,
            missing_evidence=True,
            rewrite_targets=["atom-b"],
            notes="backfill evidence",
        ),
    )

    report = weekly_review_service.generate(wiki)

    assert "feedback_issue" in report.summary
    assert "backfill evidence" in report.suggested_actions[0]
