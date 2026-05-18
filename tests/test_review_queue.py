import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository


def test_compile_apply_creates_review_queue_item_for_missing_evidence(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-source-3",
            topic="testing",
            problem_cluster="cluster-c",
            content="# Source three",
            source_refs=[],
        ),
    )

    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-review",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-c",
            content="# Atom review",
            source_refs=["personal-1:raw-source-3"],
            evidence_note="needs-more-evidence",
        ),
    )

    queue_path = temp_wiki_root / "review_queue.jsonl"
    assert queue_path.exists()
    item = json.loads(queue_path.read_text().strip())
    assert item["item_type"] == "missing_evidence"
    assert item["doc_id"] == "atom-review"


def test_review_queue_appends_with_enriched_fields(temp_wiki_root: Path) -> None:
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({
        "item_id": "rq-001",
        "wiki_id": "personal-1",
        "item_type": "compile_suggestion",
        "priority": 2,
        "created_at": "2026-05-16T10:00:00Z",
        "status": "open",
        "content_state": {"topic": "caching", "problem_cluster": "invalidation"},
    })

    items = queue.read_all()
    assert len(items) == 1
    assert items[0]["item_id"] == "rq-001"
    assert items[0]["priority"] == 2
    assert items[0]["created_at"] == "2026-05-16T10:00:00Z"
    assert items[0]["content_state"]["topic"] == "caching"


def test_review_queue_status_transitions(temp_wiki_root: Path) -> None:
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({"item_id": "rq-002", "item_type": "dispute", "status": "open"})

    assert queue.transition("rq-002", "assigned") is True
    assert queue.find("rq-002")["status"] == "assigned"

    assert queue.transition("rq-002", "in_progress") is True
    assert queue.find("rq-002")["status"] == "in_progress"

    assert queue.transition("rq-002", "resolved") is True
    assert queue.find("rq-002")["status"] == "resolved"

    assert queue.transition("rq-002", "archived") is True
    assert queue.find("rq-002")["status"] == "archived"


def test_review_queue_invalid_transition_rejected(temp_wiki_root: Path) -> None:
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({"item_id": "rq-003", "item_type": "dispute", "status": "open"})

    assert queue.transition("rq-003", "resolved") is False
    assert queue.find("rq-003")["status"] == "open"


def test_review_queue_consume_assigns_open_item_to_actor(temp_wiki_root: Path) -> None:
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({"item_id": "compile_suggestion:agents:memory:0001", "item_type": "compile_suggestion", "status": "open"})

    item = queue.consume("compile_suggestion", actor_id="claude-code")

    assert item is not None
    assert item["item_id"] == "compile_suggestion:agents:memory:0001"
    stored = queue.find("compile_suggestion:agents:memory:0001")
    assert stored["status"] == "assigned"
    assert stored["assigned_to"] == "claude-code"
    assert stored["claimed_at"]


def test_review_queue_consume_skips_nonmatching_items(temp_wiki_root: Path) -> None:
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({"item_id": "quality_signal:q1", "item_type": "quality_signal", "status": "open"})

    assert queue.consume("compile_suggestion", actor_id="claude-code") is None
    assert queue.find("quality_signal:q1")["status"] == "open"



def test_queue_producers_write_item_ids_for_detected_signals(temp_wiki_root: Path) -> None:
    import json

    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.application.compile_suggest import CompileSuggestService
    from agent_wiki.application.fast_feedback import FastFeedbackService
    from agent_wiki.application.query import QueryInput, QueryService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    for i in range(3):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-queue-{i}",
                topic="logging",
                problem_cluster="cluster-queue",
                content=f"# queue {i}",
                source_refs=[],
            ),
        )
    for _ in range(3):
        QueryService().execute(wiki=wiki, actor=actor, data=QueryInput(query="queue-gap"))

    CompileSuggestService().detect_and_enqueue(wiki)
    FastFeedbackService().detect_and_enqueue(wiki)

    entries = [json.loads(line) for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert entries
    assert all(entry.get("item_id") for entry in entries)



def test_feedback_and_propagation_queue_items_include_core_schema_fields(temp_wiki_root: Path) -> None:
    from agent_wiki.application.feedback import FeedbackInput, FeedbackService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-queue-core-1",
            topic="testing",
            problem_cluster="cluster-queue-core",
            content="# queue core",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-queue-core-1",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-queue-core",
            content="# Atom queue core",
            source_refs=["personal-1:raw-queue-core-1"],
            evidence_note="needs more proof",
        ),
    )
    FeedbackService().record(
        wiki,
        FeedbackInput(
            query_id="qid-1",
            approved=False,
            missing_evidence=True,
            rewrite_targets=["atom-queue-core-1"],
            notes="missing evidence",
        ),
    )

    entries = [json.loads(line) for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert entries
    for entry in entries:
        assert entry.get("item_id")
        assert entry.get("wiki_id")
        assert entry.get("status") == "open"
        assert entry.get("priority") is not None
        assert entry.get("created_at")
        assert entry.get("content_state") is not None


def test_review_queue_consume_uses_priority_then_created_at(temp_wiki_root: Path) -> None:
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({
        "item_id": "compile_suggestion:low",
        "item_type": "compile_suggestion",
        "status": "open",
        "priority": 2,
        "created_at": "2026-05-16T10:00:00Z",
    })
    queue.append({
        "item_id": "compile_suggestion:p0-newer",
        "item_type": "compile_suggestion",
        "status": "open",
        "priority": 0,
        "priority_label": "P0",
        "created_at": "2026-05-16T11:00:00Z",
    })
    queue.append({
        "item_id": "compile_suggestion:p0-older",
        "item_type": "compile_suggestion",
        "status": "open",
        "priority": 0,
        "priority_label": "P0",
        "created_at": "2026-05-16T09:00:00Z",
    })

    item = queue.consume("compile_suggestion", actor_id="claude-code")

    assert item is not None
    assert item["item_id"] == "compile_suggestion:p0-older"


def test_review_queue_consume_supports_priority_filter(temp_wiki_root: Path) -> None:
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({"item_id": "compile_suggestion:p1", "item_type": "compile_suggestion", "status": "open", "priority": 1, "priority_label": "P1"})
    queue.append({"item_id": "compile_suggestion:p0", "item_type": "compile_suggestion", "status": "open", "priority": 0, "priority_label": "P0"})

    item = queue.consume("compile_suggestion", actor_id="claude-code", priority_filter="P0")

    assert item is not None
    assert item["item_id"] == "compile_suggestion:p0"
    assert queue.find("compile_suggestion:p1")["status"] == "open"


def test_review_queue_can_mark_item_failed(temp_wiki_root: Path) -> None:
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({"item_id": "compile_suggestion:fail", "item_type": "compile_suggestion", "status": "open"})
    queue.consume("compile_suggestion", actor_id="claude-code")

    assert queue.mark_failed("compile_suggestion:fail", "LLM output missing content") is True

    stored = queue.find("compile_suggestion:fail")
    assert stored["status"] == "failed"
    assert stored["last_error"] == "LLM output missing content"
    assert stored["failed_at"]


def test_review_queue_recovers_assigned_items_after_timeout(temp_wiki_root: Path) -> None:
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({
        "item_id": "compile_suggestion:stale",
        "item_type": "compile_suggestion",
        "status": "assigned",
        "assigned_to": "hermes",
        "claimed_at": "2026-05-18T09:00:00Z",
    })
    queue.append({
        "item_id": "compile_suggestion:fresh",
        "item_type": "compile_suggestion",
        "status": "assigned",
        "assigned_to": "hermes",
        "claimed_at": "2026-05-18T09:45:00Z",
    })
    queue.append({
        "item_id": "compile_suggestion:progress",
        "item_type": "compile_suggestion",
        "status": "in_progress",
        "assigned_to": "hermes",
        "claimed_at": "2026-05-18T09:00:00Z",
    })

    recovered = queue.recover_assigned_timeouts(now="2026-05-18T10:00:00Z", timeout_minutes=30)

    assert recovered == 1
    stale = queue.find("compile_suggestion:stale")
    fresh = queue.find("compile_suggestion:fresh")
    progress = queue.find("compile_suggestion:progress")
    assert stale["status"] == "open"
    assert stale["previous_assigned_to"] == "hermes"
    assert stale["timeout_recovered_at"] == "2026-05-18T10:00:00Z"
    assert "assigned_to" not in stale
    assert "claimed_at" not in stale
    assert fresh["status"] == "assigned"
    assert progress["status"] == "in_progress"
