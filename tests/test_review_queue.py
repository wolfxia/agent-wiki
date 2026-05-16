import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


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
