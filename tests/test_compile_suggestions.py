from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_suggest import CompileSuggestService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_raw_accumulation_creates_compile_suggestion(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # Capture 3 raw pages in the same cluster
    for i in range(3):
        capture_service.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-suggest-{i}",
                topic="deployment",
                problem_cluster="canary-release",
                content=f"# Raw suggestion {i}\n\nEvidence {i}.",
                source_refs=[],
            ),
        )

    suggest_service = CompileSuggestService()
    candidates = suggest_service.detect(wiki)

    assert len(candidates) >= 1
    assert candidates[0]["topic"] == "deployment"
    assert candidates[0]["problem_cluster"] == "canary-release"
    assert candidates[0]["raw_count"] >= 3


def test_no_suggestion_below_threshold(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # Only 1 raw page — below default threshold of 3
    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-solo-1",
            topic="solo-topic",
            problem_cluster="solo-cluster",
            content="# Solo raw\n\nOnly one.",
            source_refs=[],
        ),
    )

    suggest_service = CompileSuggestService()
    candidates = suggest_service.detect(wiki)

    assert len(candidates) == 0
