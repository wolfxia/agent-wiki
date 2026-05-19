import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.feedback import FeedbackInput, FeedbackService
from agent_wiki.application.quality_report import QualityReportService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


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
    assert (temp_wiki_root / "feedback_outcomes.jsonl").exists()
    assert not (temp_wiki_root / "query_outcomes.jsonl").exists()


def test_feedback_does_not_pollute_query_metrics(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-feedback-metrics-1",
            topic="feedback",
            problem_cluster="metrics",
            content="# Raw feedback metrics",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-feedback-metrics-1",
            page_type="atom",
            topic="feedback",
            problem_cluster="metrics",
            summary="Feedback metrics atom.",
            aliases=["feedback metrics"],
            confidence="high",
            wikilinks=["[[raw-feedback-metrics-1]]"],
            content="# Feedback metrics\n\nFeedback metrics answer.",
            source_refs=["personal-1:raw-feedback-metrics-1"],
        ),
    )
    QueryService().execute(wiki=wiki, actor=actor, data=QueryInput(query="Feedback metrics answer"))
    FeedbackService().record(
        wiki,
        FeedbackInput(
            query_id="feedback-only-metrics",
            approved=True,
            missing_evidence=False,
            accepted_doc_ids=["atom-feedback-metrics-1"],
        ),
    )

    report = QualityReportService().generate(wiki)

    assert report["query_count"] == 1
    assert report["hit_rate"] == 1.0


def test_negative_feedback_updates_query_labels_and_creates_review_item(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-feedback-1",
            topic="feedback",
            problem_cluster="ranking",
            content="# Raw feedback",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-feedback-1",
            page_type="atom",
            topic="feedback",
            problem_cluster="ranking",
            summary="Feedback ranking result.",
            aliases=["feedback"],
            confidence="high",
            wikilinks=["[[raw-feedback-1]]"],
            content="# Atom feedback\n\nFeedback ranking result.",
            source_refs=["personal-1:raw-feedback-1"],
        ),
    )
    QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="feedback ranking"),
    )
    outcomes = [
        json.loads(line)
        for line in (temp_wiki_root / "query_outcomes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    query_id = outcomes[-1]["query_id"]

    result = FeedbackService().record(
        wiki,
        FeedbackInput(
            query_id=query_id,
            approved=False,
            missing_evidence=False,
            rewrite_targets=["atom-feedback-1"],
            rejected_doc_ids=["atom-feedback-1"],
            notes="ranking was misleading",
        ),
    )

    assert result.created_review_item is True

    updated_outcomes = [
        json.loads(line)
        for line in (temp_wiki_root / "query_outcomes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    query_entry = next(entry for entry in updated_outcomes if entry.get("query_id") == query_id and "query" in entry)
    assert query_entry["accepted_doc_ids"] == []
    assert query_entry["rejected_doc_ids"] == ["atom-feedback-1"]

    queue_item = json.loads((temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert queue_item["item_type"] == "feedback_issue"
    assert queue_item["content_state"]["rejected_doc_ids"] == ["atom-feedback-1"]
