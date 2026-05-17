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


def test_compile_suggestions_written_to_review_queue(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    for i in range(3):
        capture_service.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-queue-{i}",
                topic="observability",
                problem_cluster="logging-gaps",
                content=f"# Raw queue {i}",
                source_refs=[],
            ),
        )

    suggest_service = CompileSuggestService()
    suggest_service.detect_and_enqueue(wiki)

    queue_path = temp_wiki_root / "review_queue.jsonl"
    entries = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    suggestions = [e for e in entries if e.get("item_type") == "compile_suggestion"]
    assert len(suggestions) >= 1
    assert suggestions[0]["topic"] == "observability"
    assert suggestions[0]["problem_cluster"] == "logging-gaps"
    assert suggestions[0]["status"] == "open"


def test_compile_suggestions_prioritized_by_purpose(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # Write purpose.md that aligns with "deployment"
    (temp_wiki_root / "purpose.md").write_text(
        "# Purpose\n\n## Topics\n\n- deployment\n",
        encoding="utf-8",
    )

    # Create 3 raw pages for non-aligned topic
    for i in range(3):
        capture_service.execute(
            wiki=wiki, actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-unaligned-{i}", topic="testing",
                problem_cluster="test-cluster",
                content=f"# Raw unaligned {i}", source_refs=[],
            ),
        )

    # Create 3 raw pages for purpose-aligned topic
    for i in range(3):
        capture_service.execute(
            wiki=wiki, actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-aligned-{i}", topic="deployment",
                problem_cluster="deploy-cluster",
                content=f"# Raw aligned {i}", source_refs=[],
            ),
        )

    suggest_service = CompileSuggestService()
    candidates = suggest_service.detect(wiki)

    # Both clusters should appear
    assert len(candidates) == 2
    # Purpose-aligned cluster should sort first
    assert candidates[0]["topic"] == "deployment"
    assert candidates[1]["topic"] == "testing"


def test_compile_suggest_detects_metadata_repair_and_undercompiled_clusters(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    for i in range(3):
        capture_service.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-undercompiled-{i}",
                topic="platform",
                problem_cluster="migration",
                content=f"# Raw undercompiled {i}\n\nEvidence {i}.",
                source_refs=[],
            ),
        )

    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    pending_root = temp_wiki_root / ".agent-wiki"
    pending_root.mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "raw-needs-repair.md").write_text(
        "# Needs repair\n\nImported body.", encoding="utf-8"
    )
    (pending_root / "pending_manifest.jsonl").write_text(
        json.dumps(
            {
                "doc_id": "raw-needs-repair",
                "page_type": "raw",
                "vault_relative_path": "imports/raw-needs-repair.md",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    candidates = CompileSuggestService().detect(wiki)

    assert any(candidate["kind"] == "needs_metadata_repair" for candidate in candidates)
    assert any(candidate["kind"] == "undercompiled_cluster" for candidate in candidates)
