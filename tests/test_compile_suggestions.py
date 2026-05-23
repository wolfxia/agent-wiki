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


def test_capture_raw_suggestion_detection_ignores_malformed_review_queue_lines(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    queue_path = temp_wiki_root / "review_queue.jsonl"
    queue_path.write_text("not-json\n", encoding="utf-8")

    result = CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-malformed-queue-1",
            topic="agent-wiki",
            problem_cluster="retrieval-self-eval",
            summary="Malformed queue should not break capture.",
            content="# Malformed queue\n\nCapture still commits.",
            source_refs=[],
        ),
    )

    assert result.status == "committed"


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


def test_compile_suggest_groups_large_cluster_into_subclusters(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    for index in range(7):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-subcluster-{index}",
                topic="edge-ai",
                problem_cluster="imaging",
                content=f"# Raw Subcluster {index}",
                source_refs=[],
            ),
        )

    candidates = CompileSuggestService().detect(wiki, threshold=3)
    subclusters = [candidate for candidate in candidates if candidate.get("topic") == "edge-ai"]

    assert [candidate["sub_cluster_id"] for candidate in subclusters] == [
        "edge-ai_imaging_0001",
        "edge-ai_imaging_0002",
        "edge-ai_imaging_0003",
    ]
    assert [candidate["raw_doc_ids"] for candidate in subclusters] == [
        ["raw-subcluster-0", "raw-subcluster-1", "raw-subcluster-2"],
        ["raw-subcluster-3", "raw-subcluster-4", "raw-subcluster-5"],
        ["raw-subcluster-6"],
    ]


def test_compile_suggestions_queue_contains_prepare_payload(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    for index in range(3):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-prepare-queue-{index}",
                topic="agents",
                problem_cluster="working-memory",
                content=f"# Raw Prepare Queue {index}",
                source_refs=[],
            ),
        )

    CompileSuggestService().detect_and_enqueue(wiki)

    entries = [json.loads(line) for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    suggestion = next(entry for entry in entries if entry.get("item_type") == "compile_suggestion")
    assert suggestion["sub_cluster_id"] == "agents_working-memory_0001"
    assert suggestion["raw_doc_ids"] == ["raw-prepare-queue-0", "raw-prepare-queue-1", "raw-prepare-queue-2"]
    assert suggestion["prepare_params"] == {
        "topic": "agents",
        "problem_cluster": "working-memory",
        "doc_ids": ["raw-prepare-queue-0", "raw-prepare-queue-1", "raw-prepare-queue-2"],
        "sub_cluster_index": 1,
    }


def test_compile_suggestion_item_ids_include_subcluster_index(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    for index in range(7):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-queue-subcluster-{index}",
                topic="edge-ai",
                problem_cluster="imaging",
                content=f"# Raw Queue Subcluster {index}",
                source_refs=[],
            ),
        )

    CompileSuggestService().detect_and_enqueue(wiki, threshold=3)

    entries = [
        json.loads(line)
        for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    suggestions = [entry for entry in entries if entry.get("item_type") == "compile_suggestion"]

    assert [entry["item_id"] for entry in suggestions] == [
        "compile_suggestion:edge-ai:imaging:0001",
        "compile_suggestion:edge-ai:imaging:0002",
        "compile_suggestion:edge-ai:imaging:0003",
    ]
    assert [entry["sub_cluster_id"] for entry in suggestions] == [
        "edge-ai_imaging_0001",
        "edge-ai_imaging_0002",
        "edge-ai_imaging_0003",
    ]


def test_detect_and_enqueue_removes_old_format_compile_suggestions(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    queue_path = temp_wiki_root / "review_queue.jsonl"
    queue_path.write_text(
        json.dumps(
            {
                "item_id": "compile_suggestion:edge-ai:imaging",
                "item_type": "compile_suggestion",
                "topic": "edge-ai",
                "problem_cluster": "imaging",
                "status": "open",
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps(
            {
                "item_id": "feedback_issue:q1",
                "item_type": "feedback_issue",
                "status": "open",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    for index in range(3):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-old-queue-cleanup-{index}",
                topic="edge-ai",
                problem_cluster="imaging",
                content=f"# Raw Old Queue Cleanup {index}",
                source_refs=[],
            ),
        )

    CompileSuggestService().detect_and_enqueue(wiki, threshold=3)

    entries = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert not any(entry.get("item_id") == "compile_suggestion:edge-ai:imaging" for entry in entries)
    assert any(entry.get("item_id") == "feedback_issue:q1" for entry in entries)
    suggestion = next(entry for entry in entries if entry.get("item_id") == "compile_suggestion:edge-ai:imaging:0001")
    assert suggestion["sub_cluster_id"] == "edge-ai_imaging_0001"
    assert suggestion["raw_doc_ids"] == [
        "raw-old-queue-cleanup-0",
        "raw-old-queue-cleanup-1",
        "raw-old-queue-cleanup-2",
    ]
    assert suggestion["prepare_params"] == {
        "topic": "edge-ai",
        "problem_cluster": "imaging",
        "doc_ids": [
            "raw-old-queue-cleanup-0",
            "raw-old-queue-cleanup-1",
            "raw-old-queue-cleanup-2",
        ],
        "sub_cluster_index": 1,
    }


def test_compile_suggestions_prioritize_purpose_aligned_clusters(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "purpose.md").write_text(
        "# Purpose\n\n## Topics\n\n- imaging-os\n- agent-os\n",
        encoding="utf-8",
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    capture_service = CaptureRawService()
    for topic, prefix in [("imaging-os", "p0"), ("misc-topic", "p1")]:
        for index in range(3):
            capture_service.execute(
                wiki=wiki,
                actor=actor,
                data=CaptureRawInput(
                    doc_id=f"raw-{prefix}-{index}",
                    topic=topic,
                    problem_cluster="cluster-priority",
                    content=f"# Raw {topic} {index}",
                    source_refs=[],
                ),
            )

    candidates = CompileSuggestService().detect(wiki)

    assert candidates[0]["topic"] == "imaging-os"
    assert candidates[0]["priority"] == 0
    assert candidates[0]["priority_label"] == "P0"
    assert candidates[1]["priority"] == 1


def test_compile_suggestion_reopens_resolved_subcluster_when_raw_count_changes(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    capture_service = CaptureRawService()
    for index in range(4):
        capture_service.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-incremental-{index}",
                topic="edge-ai",
                problem_cluster="imaging",
                content=f"# Raw incremental {index}",
                source_refs=[],
            ),
        )

    service = CompileSuggestService()
    service.detect_and_enqueue(wiki, threshold=3)

    queue_path = temp_wiki_root / "review_queue.jsonl"
    entries = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    subcluster_two = next(entry for entry in entries if entry.get("item_id") == "compile_suggestion:edge-ai:imaging:0002")
    subcluster_two["status"] = "resolved"
    subcluster_two["resolved_at"] = "2026-05-20T00:00:00Z"
    queue_path.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries), encoding="utf-8")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-incremental-4",
            topic="edge-ai",
            problem_cluster="imaging",
            content="# Raw incremental 4",
            source_refs=[],
        ),
    )

    service.detect_and_enqueue(wiki, threshold=3)

    entries = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    subcluster_two = next(entry for entry in entries if entry.get("item_id") == "compile_suggestion:edge-ai:imaging:0002")
    assert subcluster_two["status"] == "open"
    assert subcluster_two["raw_doc_ids"] == ["raw-incremental-3", "raw-incremental-4"]
