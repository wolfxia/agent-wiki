from pathlib import Path
import json
from datetime import UTC, datetime, timedelta

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.maintenance import MaintenanceService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


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


def test_maintenance_compile_suggestions_include_strategy_score_and_deep_rounds(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "purpose.md").write_text("# Purpose\n\n## Topics\n- core-topic\n", encoding="utf-8")
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    for index in range(5):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-deep-{index}",
                topic="core-topic",
                problem_cluster="deep-cluster",
                content=f"# Raw deep {index}\n\nContradiction marker conflict {index}.",
                source_refs=[],
            ),
        )
    for index in range(4):
        QueryService().execute(wiki=wiki, actor=actor, data=QueryInput(query="core-topic deep-cluster"))
    (temp_wiki_root / "review_queue.jsonl").write_text(
        json.dumps(
            {
                "item_id": "compile_suggestion:old-failed",
                "item_type": "compile_suggestion",
                "status": "failed",
                "topic": "core-topic",
                "problem_cluster": "deep-cluster",
                "content_state": {"error_type": "quality_rejected"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = MaintenanceService().run(wiki)

    queue_entries = [
        json.loads(line)
        for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    suggestion = next(
        entry
        for entry in queue_entries
        if entry.get("item_type") == "compile_suggestion" and entry.get("problem_cluster") == "deep-cluster"
    )
    assert suggestion["compile_strategy"] == "Deep"
    assert suggestion["compile_priority_score"] >= 80
    assert suggestion["deep_compile_rounds"] == 3
    assert summary["compile_strategy_counts"]["Deep"] >= 1


def test_maintenance_reports_post_compile_uplift_atom_reference_rate_and_staleness_governance(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-value-1",
            topic="value",
            problem_cluster="cluster-value",
            content="# Raw value",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-value-1",
            page_type="atom",
            topic="value",
            problem_cluster="cluster-value",
            summary="Value atom.",
            aliases=["value"],
            confidence="high",
            wikilinks=["[[raw-value-1]]"],
            content="# Atom value\n\n## Claims\n- Claim.\n\n## Evidence\n- Evidence.",
            source_refs=["personal-1:raw-value-1"],
        ),
    )
    stale_ts = (datetime.now(UTC) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    manifest_entries = [json.loads(line) for line in (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8").splitlines()]
    for entry in manifest_entries:
        if entry.get("doc_id") == "atom-value-1":
            entry["updated_at"] = stale_ts
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in manifest_entries),
        encoding="utf-8",
    )
    runtime_root = temp_wiki_root / ".agent-wiki"
    runtime_root.mkdir(exist_ok=True)
    (runtime_root / "eval_history.jsonl").write_text(
        "".join(
            json.dumps(entry, ensure_ascii=False) + "\n"
            for entry in [
                {"timestamp": "2026-05-18T00:00:00Z", "metrics": {"strict_recall_at_k": 0.40}},
                {"timestamp": "2026-05-19T00:00:00Z", "metrics": {"strict_recall_at_k": 0.55}},
            ]
        ),
        encoding="utf-8",
    )
    (temp_wiki_root / "query_outcomes.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "query_id": f"value-q-{index}",
                    "query": "value cluster",
                    "hit_count": 1,
                    "accepted_doc_ids": ["atom-value-1"],
                    "rejected_doc_ids": [],
                },
                ensure_ascii=False,
            )
            + "\n"
            for index in range(3)
        ),
        encoding="utf-8",
    )

    summary = MaintenanceService().run(wiki)

    assert summary["value_metrics"]["post_compile_query_uplift"] == 0.15
    assert summary["value_metrics"]["atom_reference_rate"] == 1.0
    assert summary["staleness_governance"]["hot_stale_doc_ids"] == ["atom-value-1"]
    queue_entries = [
        json.loads(line)
        for line in (temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(entry.get("item_type") == "staleness_refresh" for entry in queue_entries)


def test_maintenance_runs_capped_incremental_claim_annotation(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    for index in range(60):
        doc_id = f"atom-maint-claim-{index}"
        (pages / f"{doc_id}.md").write_text(f"# Atom {index}\n\n## Claims\n- Claim {index}.\n", encoding="utf-8")
        ManifestRepository(temp_wiki_root).upsert({
            "wiki_id": "personal-1",
            "doc_id": doc_id,
            "page_type": "atom",
            "canonical_uri": f"pages/{doc_id}.md",
        })

    summary = MaintenanceService().run(wiki)

    assert summary["claim_annotations"]["annotated_count"] == 50
    annotations = [
        json.loads(line)
        for line in (temp_wiki_root / ".agent-wiki" / "claim_annotations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(annotations) == 50


def test_maintenance_rebuild_index_optionally_builds_vector_index(monkeypatch, temp_wiki_root: Path) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-embed-rebuild-1",
            topic="embedding",
            problem_cluster="rebuild",
            content="# Raw embed rebuild",
            source_refs=[],
        ),
    )

    captured: dict[str, int] = {"embedded_count": 0}

    class FakeVectorIndex:
        def rebuild_from_manifest(self, manifest_entries, embedding_provider=None):
            captured["embedded_count"] = len(manifest_entries)
            return len(manifest_entries)

    monkeypatch.setattr("agent_wiki.application.maintenance.SQLiteVectorIndexProvider", lambda *args, **kwargs: FakeVectorIndex())

    result = MaintenanceService().rebuild_index(wiki, include_embedding=True)

    assert result["embedded_count"] == 1
    assert captured["embedded_count"] == 1


def test_maintenance_incrementally_embeds_updated_manifest_entries(monkeypatch, temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "atom-embed-1.md").write_text("# Atom\n\nsemantic retrieval content", encoding="utf-8")
    ManifestRepository(temp_wiki_root).upsert({
        "wiki_id": "personal-1",
        "doc_id": "atom-embed-1",
        "page_type": "atom",
        "canonical_uri": "pages/atom-embed-1.md",
        "updated_at": "2026-05-20T00:00:00Z",
    })

    captured: list[tuple[str, str]] = []

    class FakeVectorIndex:
        def upsert(self, doc_id: str, payload: dict) -> None:
            captured.append((doc_id, payload.get("updated_at") or ""))

    class FakeEmbeddingProvider:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr("agent_wiki.application.maintenance.SQLiteVectorIndexProvider", lambda *args, **kwargs: FakeVectorIndex())
    monkeypatch.setattr(MaintenanceService, "_embedding_provider_from_wiki", lambda self, wiki: FakeEmbeddingProvider())

    first = MaintenanceService().run(wiki)
    second = MaintenanceService().run(wiki)

    assert first["embedding_maintenance"]["embedded_count"] == 1
    assert second["embedding_maintenance"]["embedded_count"] == 0
    assert captured == [("atom-embed-1", "2026-05-20T00:00:00Z")]


def test_maintenance_incremental_embedding_failure_falls_back_without_crash(monkeypatch, temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "atom-embed-fail-1.md").write_text("# Atom\n\nsemantic retrieval content", encoding="utf-8")
    ManifestRepository(temp_wiki_root).upsert({
        "wiki_id": "personal-1",
        "doc_id": "atom-embed-fail-1",
        "page_type": "atom",
        "canonical_uri": "pages/atom-embed-fail-1.md",
        "updated_at": "2026-05-20T00:00:00Z",
    })

    class FailingEmbeddingProvider:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(MaintenanceService, "_embedding_provider_from_wiki", lambda self, wiki: FailingEmbeddingProvider())

    summary = MaintenanceService().run(wiki)

    assert summary["embedding_maintenance"]["embedded_count"] == 0




def test_maintenance_auto_tune_runs_post_change_eval_and_rolls_back(monkeypatch, temp_wiki_root: Path) -> None:
    import agent_wiki.application.maintenance as maintenance_module

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={
            "workspace_path": str(temp_wiki_root),
            "tuning_defaults": {"query_ranking": {"topic_alignment_boost": 6.5}},
        }
    )
    runtime_root = temp_wiki_root / ".agent-wiki"
    runtime_root.mkdir(exist_ok=True)
    (runtime_root / "eval_history.jsonl").write_text(
        "".join(
            json.dumps(entry, ensure_ascii=False) + "\n"
            for entry in [
                {"timestamp": "2026-05-18T00:00:00Z", "metrics": {"strict_recall_at_k": 0.80}},
                {"timestamp": "2026-05-19T00:00:00Z", "metrics": {"strict_recall_at_k": 0.70}},
            ]
        ),
        encoding="utf-8",
    )
    eval_dir = temp_wiki_root / "eval"
    eval_dir.mkdir(exist_ok=True)
    (eval_dir / "retrieval_queries.jsonl").write_text(
        json.dumps({"query": "auto tune", "expected_doc_ids": [], "acceptable_doc_ids": [], "must_not_doc_ids": []}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    eval_reports = [
        {"metrics": {"strict_recall_at_k": 0.70}},
        {"metrics": {"strict_recall_at_k": 0.67}},
    ]

    class FakeEvalRetrievalService:
        def run(self, **kwargs):
            return eval_reports.pop(0)

    monkeypatch.setattr(maintenance_module, "EvalRetrievalService", lambda: FakeEvalRetrievalService())

    summary = MaintenanceService().run(wiki, auto_tune=True)

    assert summary["auto_tune"]["status"] == "rolled_back"
    assert summary["auto_tune"]["eval_after"]["metrics"]["strict_recall_at_k"] == 0.67
    assert eval_reports == []
    runtime = json.loads((runtime_root / "runtime_tuning.json").read_text(encoding="utf-8"))
    assert runtime["query_ranking"]["topic_alignment_boost"] == 6.5


def test_maintenance_reports_quality_metrics(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-metrics-pending",
            topic="metrics",
            problem_cluster="cluster-metrics",
            content="# Raw pending",
            source_refs=[],
        ),
    )
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-metrics-covered",
            topic="metrics",
            problem_cluster="cluster-metrics",
            content="# Raw covered",
            source_refs=[],
        ),
    )

    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-metrics-covered",
            page_type="atom",
            topic="metrics",
            problem_cluster="cluster-metrics",
            content="# Atom covered\n\n## Claims\n- raw-metrics-covered\n\n## Evidence\n- source.",
            summary="Atom covered",
            source_refs=["personal-1:raw-metrics-covered"],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="synthesis-metrics-1",
            page_type="synthesis",
            topic="agent-os-ai-harness",
            problem_cluster="cross-domain",
            content="# Synthesis\n\nsummary",
            summary="Synthesis",
            source_refs=["personal-1:raw-metrics-covered"],
        ),
    )

    queue = ReviewQueueRepository(temp_wiki_root)
    queue.append({
        "item_id": "compile_suggestion:metrics:pending",
        "item_type": "compile_suggestion",
        "status": "open",
        "raw_doc_ids": ["raw-metrics-pending"],
    })

    stale_ts = (datetime.now(UTC) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    manifest_entries = [
        json.loads(line)
        for line in (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for entry in manifest_entries:
            if entry.get("doc_id") == "atom-metrics-covered":
                entry["created_at"] = stale_ts
                entry["updated_at"] = stale_ts
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in manifest_entries),
        encoding="utf-8",
    )

    summary = MaintenanceService().run(wiki)

    metrics = summary["quality_metrics"]
    assert metrics["compile_pending"] >= 1
    assert metrics["compile_coverage"] == 0.5
    assert metrics["freshness_distribution"]["stale"] >= 1
    assert metrics["synthesis_directions"] >= 1
    assert 0.0 <= metrics["claim_annotation_coverage"] <= 1.0


def test_maintenance_quality_metrics_freshness_prefers_created_at(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-created-at-metrics",
            topic="metrics",
            problem_cluster="created-at",
            content="# Raw metrics",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-created-at-metrics",
            page_type="atom",
            topic="metrics",
            problem_cluster="created-at",
            content="# Atom metrics\n\n## Claims\n- raw-created-at-metrics\n\n## Evidence\n- source.",
            summary="Atom metrics",
            source_refs=["personal-1:raw-created-at-metrics"],
        ),
    )

    stale_created_at = (datetime.now(UTC) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    recent_updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    manifest_entries = [
        json.loads(line)
        for line in (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for entry in manifest_entries:
        if entry.get("doc_id") == "atom-created-at-metrics":
            entry["created_at"] = stale_created_at
            entry["updated_at"] = recent_updated_at
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in manifest_entries),
        encoding="utf-8",
    )

    summary = MaintenanceService().run(wiki)

    metrics = summary["quality_metrics"]
    assert metrics["freshness_distribution"]["stale"] >= 1
