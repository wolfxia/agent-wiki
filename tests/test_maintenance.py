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


def test_maintenance_runs_eval_and_writes_eval_history_when_eval_file_exists(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-maint-eval-1",
            topic="agent-os",
            problem_cluster="maint-eval",
            content="# Raw maintain eval",
            source_refs=[],
        ),
    )
    eval_dir = temp_wiki_root / "eval"
    eval_dir.mkdir(exist_ok=True)
    (eval_dir / "retrieval_queries.jsonl").write_text(
        json.dumps(
            {
                "query": "maintain eval",
                "query_type": "fact",
                "expected_doc_ids": ["raw-maint-eval-1"],
                "acceptable_doc_ids": [],
                "must_not_doc_ids": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = MaintenanceService().run(wiki)

    assert "eval_baseline" in summary
    assert summary["eval_baseline"]["metrics"]["strict_recall_at_k"] == 1.0
    history_path = temp_wiki_root / ".agent-wiki" / "eval_history.jsonl"
    assert history_path.exists()
    history = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(history) == 1


def test_maintenance_eval_timeout_returns_summary_without_eval_baseline(monkeypatch, temp_wiki_root: Path) -> None:
    import json
    import time

    import agent_wiki.application.maintenance as maintenance_module

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    eval_dir = temp_wiki_root / "eval"
    eval_dir.mkdir(exist_ok=True)
    (eval_dir / "retrieval_queries.jsonl").write_text(
        json.dumps(
            {
                "query": "slow maintain eval",
                "query_type": "fact",
                "expected_doc_ids": [],
                "acceptable_doc_ids": [],
                "must_not_doc_ids": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    class SlowEvalService:
        def run(self, **kwargs):
            time.sleep(0.2)
            return {"metrics": {"strict_recall_at_k": 1.0}}

    monkeypatch.setattr(maintenance_module, "EvalRetrievalService", lambda: SlowEvalService())
    monkeypatch.setattr(maintenance_module, "_MAINTAIN_EVAL_TIMEOUT_SECONDS", 0.01)

    summary = MaintenanceService().run(wiki)

    assert "eval_baseline" not in summary
    assert summary["eval_timeout"] is True
    history_path = temp_wiki_root / ".agent-wiki" / "eval_history.jsonl"
    assert not history_path.exists()



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



def test_maintenance_cleans_orphan_manifest_and_indexes(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "raw-keep.md").write_text("# Keep\n\nKeep content.", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        '\n'.join([
            json.dumps({"wiki_id": "personal-1", "doc_id": "raw-keep", "page_type": "raw", "topic": "ops", "problem_cluster": "cleanup", "summary": "keep", "canonical_uri": "pages/raw-keep.md"}),
            json.dumps({"wiki_id": "personal-1", "doc_id": "raw-orphan", "page_type": "raw", "topic": "ops", "problem_cluster": "cleanup", "summary": "orphan", "canonical_uri": "pages/raw-orphan.md"}),
        ]) + '\n',
        encoding="utf-8",
    )
    (temp_wiki_root / "retrieval_index.jsonl").write_text(
        '{"wiki_id":"personal-1","doc_id":"raw-keep","page_type":"raw","topic":"ops","problem_cluster":"cleanup","content":"keep"}\n'
        '{"wiki_id":"personal-1","doc_id":"raw-orphan","page_type":"raw","topic":"ops","problem_cluster":"cleanup","content":"orphan"}\n',
        encoding="utf-8",
    )
    (temp_wiki_root / "topic_index.md").write_text(
        "| doc_id | page_type | topic | problem_cluster | summary |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| raw-keep | raw | ops | cleanup | keep |\n"
        "| raw-orphan | raw | ops | cleanup | orphan |\n",
        encoding="utf-8",
    )

    summary = MaintenanceService().run(wiki)

    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    retrieval = (temp_wiki_root / "retrieval_index.jsonl").read_text(encoding="utf-8")
    topic_index = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
    operations = [json.loads(line) for line in (temp_wiki_root / "operation_log.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    assert summary["orphan_cleanup_count"] == 1
    assert "raw-keep" in manifest
    assert "raw-orphan" not in manifest
    assert "raw-keep" in retrieval
    assert "raw-orphan" not in retrieval
    assert "raw-keep" in topic_index
    assert "raw-orphan" not in topic_index
    assert any(entry.get("operation") == "orphan_cleanup" and entry.get("doc_id") == "raw-orphan" for entry in operations)


def test_maintenance_recovers_timed_out_assigned_queue_items(temp_wiki_root: Path) -> None:
    import json

    from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({
        "item_id": "compile_suggestion:maint-stale",
        "item_type": "compile_suggestion",
        "status": "assigned",
        "assigned_to": "hermes",
        "claimed_at": "2000-01-01T00:00:00Z",
    })

    summary = MaintenanceService().run(wiki)

    assert summary["queue_timeouts_recovered"] == 1
    items = [json.loads(line) for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    item = next(entry for entry in items if entry["item_id"] == "compile_suggestion:maint-stale")
    assert item["status"] == "open"
    assert item["previous_assigned_to"] == "hermes"


def test_maintenance_enqueues_duplicate_atom_warnings(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-dup-1",
            topic="dup",
            problem_cluster="cluster-dup",
            content="# Raw dup one",
            source_refs=[],
        ),
    )
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-dup-2",
            topic="dup",
            problem_cluster="cluster-dup",
            content="# Raw dup two",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-dup-1",
            page_type="atom",
            topic="dup",
            problem_cluster="cluster-dup",
            summary="The agent caches compile summaries for repeated query ranking diagnosis.",
            aliases=["dup"],
            confidence="high",
            wikilinks=["[[raw-dup-1]]"],
            content="# Atom dup one\n\n## Claims\n- Claim.\n\n## Evidence\n- Evidence.",
            source_refs=["personal-1:raw-dup-1"],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-dup-2",
            page_type="atom",
            topic="dup",
            problem_cluster="cluster-dup",
            summary="The agent caches compile summaries for repeated query ranking diagnosis flows.",
            aliases=["dup-two"],
            confidence="high",
            wikilinks=["[[raw-dup-2]]"],
            content="# Atom dup two\n\n## Claims\n- Claim.\n\n## Evidence\n- Evidence.",
            source_refs=["personal-1:raw-dup-2"],
        ),
    )

    summary = MaintenanceService().run(wiki)

    assert summary["duplicate_atom_warnings"] == 1
    queue_entries = [
        json.loads(line)
        for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    duplicate_item = next(entry for entry in queue_entries if entry.get("item_type") == "duplicate_atom_warning")
    assert duplicate_item["content_state"]["doc_ids"] == ["atom-dup-1", "atom-dup-2"]
