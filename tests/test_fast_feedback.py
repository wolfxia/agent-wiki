import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.fast_feedback import FastFeedbackService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_repeated_zero_hit_queries_trigger_quality_signal(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # Generate 3 zero-hit queries
    for _ in range(3):
        query_service.execute(
            wiki=wiki,
            actor=actor,
            data=QueryInput(query="nonexistent-xyz-topic"),
        )

    feedback_service = FastFeedbackService()
    signals = feedback_service.detect_low_value_queries(wiki)

    assert len(signals) >= 1
    assert signals[0]["query"] == "nonexistent-xyz-topic"
    assert signals[0]["zero_hit_count"] >= 3


def test_no_signal_for_successful_queries(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-ff-1",
            topic="feedback",
            problem_cluster="cluster-ff",
            content="# Raw feedback\n\nContent about feedback.",
            source_refs=[],
        ),
    )

    # Queries that produce hits
    for _ in range(3):
        query_service.execute(
            wiki=wiki,
            actor=actor,
            data=QueryInput(query="feedback"),
        )

    feedback_service = FastFeedbackService()
    signals = feedback_service.detect_low_value_queries(wiki)

    assert len(signals) == 0


def test_fast_feedback_signals_written_to_review_queue(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    for _ in range(3):
        query_service.execute(
            wiki=wiki,
            actor=actor,
            data=QueryInput(query="missing-knowledge-gap"),
        )

    feedback_service = FastFeedbackService()
    feedback_service.detect_and_enqueue(wiki)

    queue_path = temp_wiki_root / "review_queue.jsonl"
    entries = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    signals = [e for e in entries if e.get("item_type") == "quality_signal"]
    assert len(signals) >= 1
    assert signals[0]["query"] == "missing-knowledge-gap"
    assert signals[0]["status"] == "open"
