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
