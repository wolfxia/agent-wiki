from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.maintenance import MaintenanceService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_maintenance_runs_all_detectors_and_returns_summary(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # 3 raw pages in same cluster → triggers compile_suggestion
    for i in range(3):
        capture_service.execute(
            wiki=wiki, actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-maint-{i}", topic="logging",
                problem_cluster="cluster-maint",
                content=f"# Raw maint {i}", source_refs=[],
            ),
        )

    # 3 zero-hit queries → triggers quality_signal
    for _ in range(3):
        query_service.execute(
            wiki=wiki, actor=actor,
            data=QueryInput(query="nonexistent-knowledge-gap"),
        )

    # Two pages co-occurring in queries → triggers signal_candidate
    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-co-1", topic="caching", problem_cluster="cluster-co",
            content="# Raw co 1", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-co-1", page_type="atom", topic="caching",
            problem_cluster="cluster-co",
            content="# Atom co one\n\nCaching invalidation strategies.",
            source_refs=["personal-1:raw-co-1"],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-co-2", page_type="atom", topic="caching",
            problem_cluster="cluster-co",
            content="# Atom co two\n\nCaching invalidation patterns.",
            source_refs=["personal-1:raw-co-1"],
        ),
    )
    for _ in range(2):
        query_service.execute(
            wiki=wiki, actor=actor,
            data=QueryInput(query="caching invalidation"),
        )

    summary = MaintenanceService().run(wiki)

    assert summary["compile_suggestions"] >= 1
    assert summary["quality_signals"] >= 1
    assert summary["co_occurrence_candidates"] >= 1
    assert summary["cross_reference_candidates"] >= 1

    # Items actually landed in the queue
    queue_path = temp_wiki_root / "review_queue.jsonl"
    entries = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    item_types = {e.get("item_type") for e in entries}
    assert "compile_suggestion" in item_types
    assert "quality_signal" in item_types
    assert "signal_candidate" in item_types


def test_maintenance_summary_includes_action_items(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    for i in range(3):
        capture_service.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-maint-actions-{i}",
                topic="deployment",
                problem_cluster="cluster-maint-actions",
                content=f"# Raw maint actions {i}",
                source_refs=[],
            ),
        )

    for _ in range(3):
        query_service.execute(
            wiki=wiki,
            actor=actor,
            data=QueryInput(query="maintenance-gap-query"),
        )

    summary = MaintenanceService().run(wiki)

    assert "action_items" in summary
    assert any("compile" in item.lower() for item in summary["action_items"])
    assert any("maintenance-gap-query" in item for item in summary["action_items"])


def test_maintenance_idempotent_with_no_signals(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )

    summary = MaintenanceService().run(wiki)

    assert summary["compile_suggestions"] == 0
    assert summary["quality_signals"] == 0
    assert summary["co_occurrence_candidates"] == 0
    assert summary["cross_reference_candidates"] == 0



def test_maintenance_does_not_duplicate_queue_items_on_repeat_run(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    for i in range(3):
        capture_service.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-maint-dedupe-{i}",
                topic="logging",
                problem_cluster="cluster-maint-dedupe",
                content=f"# Raw dedupe {i}",
                source_refs=[],
            ),
        )

    for _ in range(3):
        query_service.execute(wiki=wiki, actor=actor, data=QueryInput(query="repeat-gap"))

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-dedupe-shared",
            topic="caching",
            problem_cluster="cluster-dedupe",
            content="# Raw dedupe shared",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-dedupe-1",
            page_type="atom",
            topic="caching",
            problem_cluster="cluster-dedupe",
            content="# Atom dedupe one\n\nCaching invalidation strategies.",
            source_refs=["personal-1:raw-dedupe-shared"],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-dedupe-2",
            page_type="atom",
            topic="caching",
            problem_cluster="cluster-dedupe",
            content="# Atom dedupe two\n\nCaching invalidation strategies.",
            source_refs=["personal-1:raw-dedupe-shared"],
        ),
    )
    for _ in range(2):
        query_service.execute(wiki=wiki, actor=actor, data=QueryInput(query="caching invalidation"))

    service = MaintenanceService()
    service.run(wiki)
    first_entries = [json.loads(line) for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    service.run(wiki)
    second_entries = [json.loads(line) for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(second_entries) == len(first_entries)


def test_maintenance_reports_metadata_repair_and_undercompiled_clusters(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    pending_root = temp_wiki_root / ".agent-wiki"
    pending_root.mkdir(exist_ok=True)
    entries: list[str] = []
    for index in range(3):
        doc_id = f"repair-maint-{index}"
        (temp_wiki_root / "pages" / f"{doc_id}.md").write_text(
            f"# Repair Maint {index}\n\nBody.", encoding="utf-8"
        )
        entries.append(
            json.dumps(
                {
                    "doc_id": doc_id,
                    "page_type": "raw",
                    "vault_relative_path": f"repair/{doc_id}.md",
                },
                ensure_ascii=False,
            )
        )
    (pending_root / "pending_manifest.jsonl").write_text("\n".join(entries) + "\n", encoding="utf-8")

    summary = MaintenanceService().run(wiki)

    assert summary["metadata_repair_candidates"] >= 1
    assert summary["compile_suggestions"] >= 1
