import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_capture_raw_writes_page_manifest_index_and_log(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    service = CaptureRawService()

    result = service.execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-capture-1",
            topic="testing",
            problem_cluster="milestone-2",
            content="# Captured raw\n\nEvidence",
            source_refs=[],
        ),
    )

    assert result.status == "committed"
    assert (temp_wiki_root / "pages" / "raw-capture-1.md").exists()
    assert (temp_wiki_root / "MANIFEST.jsonl").exists()
    assert (temp_wiki_root / "retrieval_index.jsonl").exists()
    assert (temp_wiki_root / "log.md").exists()

    retrieval_card = json.loads((temp_wiki_root / "retrieval_index.jsonl").read_text().strip())
    assert retrieval_card["doc_id"] == "raw-capture-1"
    assert retrieval_card["page_type"] == "raw"


def test_capture_raw_invalid_doc_id_goes_to_pending(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    service = CaptureRawService()

    result = service.execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="Raw Invalid",
            topic="testing",
            problem_cluster="milestone-2",
            content="# Bad raw",
            source_refs=[],
        ),
    )

    assert result.status == "pending"
    assert not (temp_wiki_root / "MANIFEST.jsonl").exists()
    pending_manifest = temp_wiki_root / ".agent-wiki" / "pending_manifest.jsonl"
    assert pending_manifest.exists()
    assert "Raw Invalid" in pending_manifest.read_text()


def test_capture_raw_denied_when_no_permission(temp_wiki_root: Path) -> None:
    from agent_wiki.bootstrap.registry_loader import PermissionConfig

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={
            "workspace_path": str(temp_wiki_root),
            "permissions": [
                PermissionConfig(
                    actor_type="agent",
                    actor_id="restricted-agent",
                    allowed_operations=["query"],
                    max_gate="A",
                    allowed_page_types=["raw"],
                )
            ],
        }
    )
    service = CaptureRawService()

    try:
        service.execute(
            wiki=wiki,
            actor=ResolvedActor(actor_type="agent", actor_id="restricted-agent", transport="cli"),
            data=CaptureRawInput(
                doc_id="raw-denied-1", topic="testing", problem_cluster="cluster-d",
                content="# Denied", source_refs=[],
            ),
        )
    except PermissionError as error:
        assert "permission" in str(error).lower() or "no matching" in str(error).lower()
    else:
        raise AssertionError("expected permission denial")


def test_capture_raw_input_allows_missing_topic_and_problem_cluster() -> None:
    payload = CaptureRawInput(
        doc_id="raw-intake-1",
        topic=None,
        problem_cluster=None,
        summary=None,
        content="# Raw intake\n\nCapture body.",
        source_refs=[],
    )

    assert payload.topic is None
    assert payload.problem_cluster is None
    assert payload.summary is None


def test_capture_raw_persists_normalized_metadata(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )

    CaptureRawService().execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-intake-1",
            topic=None,
            problem_cluster=None,
            summary=None,
            content="# Raw intake\n\nCapture body.",
            source_refs=[],
        ),
    )

    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    assert "raw-intake-1" in manifest
    assert "classification_confidence" in manifest


def test_capture_raw_enqueues_compile_suggestion_when_cluster_reaches_threshold(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "purpose.md").write_text(
        "# Purpose\n\n## Topics\n\n- imaging-os\n",
        encoding="utf-8",
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    for index in range(3):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-capture-trigger-{index}",
                topic="imaging-os",
                problem_cluster="capture-trigger",
                content=f"# Raw capture trigger {index}",
                source_refs=[],
            ),
        )

    queue_entries = [
        json.loads(line)
        for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    suggestion = next(entry for entry in queue_entries if entry.get("item_type") == "compile_suggestion")
    assert suggestion["item_id"] == "compile_suggestion:imaging-os:capture-trigger:0001"
    assert suggestion["priority_label"] == "P0"
    assert suggestion["raw_doc_ids"] == [
        "raw-capture-trigger-0",
        "raw-capture-trigger-1",
        "raw-capture-trigger-2",
    ]
