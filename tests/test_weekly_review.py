from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.feedback import FeedbackInput, FeedbackService
from agent_wiki.application.weekly_review import WeeklyReviewService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


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


def test_weekly_review_includes_raw_backlog_count(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    for i in range(5):
        capture_service.execute(
            wiki=wiki, actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-backlog-{i}", topic="testing",
                problem_cluster="cluster-bl",
                content=f"# Raw backlog {i}", source_refs=[],
            ),
        )

    report = WeeklyReviewService().generate(wiki)

    assert "5 raw" in report.summary


def test_weekly_review_includes_purpose_alignment(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )

    (temp_wiki_root / "purpose.md").write_text(
        "# Purpose\n\n## Topics\n\n- deployment\n- security\n",
        encoding="utf-8",
    )

    report = WeeklyReviewService().generate(wiki)

    assert "purpose" in report.summary.lower()
    assert "deployment" in report.summary or "security" in report.summary


def test_weekly_review_surfaces_quality_signals_and_suggestions(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )

    # Write queue items of different types
    queue_path = temp_wiki_root / "review_queue.jsonl"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    items = [
        {"item_type": "quality_signal", "query": "missing-topic", "status": "open"},
        {"item_type": "quality_signal", "query": "another-gap", "status": "open"},
        {"item_type": "compile_suggestion", "topic": "caching", "problem_cluster": "invalidation", "status": "open"},
        {"item_type": "feedback_issue", "reason": "needs more evidence", "status": "open"},
    ]
    with queue_path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")

    report = WeeklyReviewService().generate(wiki)

    assert "2 quality_signal" in report.summary
    assert "1 compile_suggestion" in report.summary
