import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.feedback import FeedbackInput, FeedbackService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.application.weekly_review import WeeklyReviewService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_capture_feedback_weekly_review_closes_the_loop(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-review-1",
            topic="review",
            problem_cluster="review-loop",
            content="# Raw review\n\nKnown evidence that should not match the gap query.",
            source_refs=[],
        ),
    )

    miss_result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="zzzznonexistenttopic"),
    )
    outcomes = [json.loads(line) for line in (temp_wiki_root / "query_outcomes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    query_id = outcomes[-1]["query_id"]

    feedback_result = FeedbackService().record(
        wiki,
        FeedbackInput(
            query_id=query_id,
            approved=False,
            missing_evidence=True,
            rewrite_targets=["raw-review-1"],
            notes="missing evidence for zero-hit question",
        ),
    )

    report = WeeklyReviewService().generate(wiki)
    queue_items = [json.loads(line) for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    assert miss_result.miss_signal is True
    assert feedback_result.created_review_item is True
    assert queue_items[-1]["item_type"] == "feedback_issue"
    assert "1 miss signals" in report.summary
    assert "feedback_issue" in report.summary
    assert any("missing evidence for zero-hit question" in action for action in report.suggested_actions)
