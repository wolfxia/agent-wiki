from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput
from agent_wiki.application.propagation import PropagationService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_propagation_service_updates_all_a_level_artifacts(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    service = PropagationService(temp_wiki_root)

    result = service.propagate_capture_raw(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-propagation-1",
            topic="testing",
            problem_cluster="milestone-2",
            content="# Raw",
            source_refs=[],
        ),
    )

    assert result.status == "committed"
    assert (temp_wiki_root / "pages" / "raw-propagation-1.md").exists()
    assert (temp_wiki_root / "MANIFEST.jsonl").exists()
    assert (temp_wiki_root / "retrieval_index.jsonl").exists()
    assert (temp_wiki_root / "log.md").exists()
