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
    assert items[0]["wiki_id"] == "personal-1"
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
