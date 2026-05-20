from pathlib import Path
import json

from typer.testing import CliRunner
import yaml

from agent_wiki.application.compile_apply import CompileStructuredOutput
from agent_wiki.transports.cli.app import app


def test_cli_entrypoint_sets_default_timeout(monkeypatch) -> None:
    import agent_wiki.transports.cli.app as cli_app

    alarms: list[int] = []

    def fake_alarm(seconds: int) -> int:
        alarms.append(seconds)
        return 0

    monkeypatch.setattr(cli_app.signal, "alarm", fake_alarm)
    monkeypatch.setattr(cli_app, "app", lambda: None)

    cli_app.main()

    assert alarms == [300, 0]


def test_cli_compile_execute_apply_increases_timeout_from_limit(monkeypatch) -> None:
    import agent_wiki.transports.cli.app as cli_app

    alarms: list[int] = []

    class FakeService:
        def apply_next(self, wiki, actor, data):
            assert data.limit == 3
            assert data.concurrency == 1
            return []

    def fake_alarm(seconds: int) -> int:
        alarms.append(seconds)
        return 0

    monkeypatch.setattr(cli_app.signal, "alarm", fake_alarm)
    monkeypatch.setattr(cli_app, "CompileExecuteService", lambda: FakeService())

    result = CliRunner().invoke(
        app,
        [
            "compile-execute",
            "--apply",
            "--limit",
            "3",
            "--workspace",
            "/tmp",
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert alarms == [420]


def test_cli_compile_execute_apply_forwards_concurrency(monkeypatch) -> None:
    import agent_wiki.transports.cli.app as cli_app

    captured: dict[str, int] = {}

    class FakeService:
        def apply_next(self, wiki, actor, data):
            captured["limit"] = data.limit
            captured["concurrency"] = data.concurrency
            return []

    monkeypatch.setattr(cli_app.signal, "alarm", lambda seconds: 0)
    monkeypatch.setattr(cli_app, "CompileExecuteService", lambda: FakeService())

    result = CliRunner().invoke(
        app,
        [
            "compile-execute",
            "--apply",
            "--limit",
            "3",
            "--concurrency",
            "2",
            "--workspace",
            "/tmp",
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert captured == {"limit": 3, "concurrency": 2}


def test_cli_help_renders() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Agent Wiki CLI" in result.stdout


def test_cli_serve_help_renders() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["serve", "--help"])

    assert result.exit_code == 0


def test_cli_serve_runs_stdio_mcp_server(monkeypatch, temp_wiki_root) -> None:
    captured: dict[str, object] = {}

    def fake_run_stdio_server(registry_path: str | None = None) -> None:
        captured["registry_path"] = registry_path

    monkeypatch.setattr("agent_wiki.transports.cli.app.run_stdio_server", fake_run_stdio_server)
    monkeypatch.setattr("agent_wiki.transports.cli.app._acquire_pidfile", lambda: None)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "serve",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
    )

    assert result.exit_code == 0
    assert captured["registry_path"] == "tests/fixtures/registry.yaml"


def test_cli_serve_skips_pidfile_with_no_pidfile_flag(monkeypatch, temp_wiki_root) -> None:
    captured: dict[str, object] = {}

    def fake_run_stdio_server(registry_path: str | None = None) -> None:
        captured["registry_path"] = registry_path

    def fail_acquire_pidfile() -> None:
        raise AssertionError("pidfile should be skipped")

    monkeypatch.setattr("agent_wiki.transports.cli.app.run_stdio_server", fake_run_stdio_server)
    monkeypatch.setattr("agent_wiki.transports.cli.app._acquire_pidfile", fail_acquire_pidfile)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "serve",
            "--no-pidfile",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
    )

    assert result.exit_code == 0
    assert captured["registry_path"] == "tests/fixtures/registry.yaml"


def test_cli_query_command(temp_wiki_root) -> None:
    from pathlib import Path
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    CaptureRawService().execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-cli-1", topic="testing", problem_cluster="cluster-cli",
            content="# Raw cli", source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-cli-1", page_type="atom", topic="testing",
            problem_cluster="cluster-cli",
            content="# Atom cli\n\nCLI query results.",
            source_refs=["personal-1:raw-cli-1"],
        ),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["query", "CLI query results", "--workspace", str(temp_wiki_root), "--registry", "tests/fixtures/registry.yaml"], env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"})

    assert result.exit_code == 0
    assert "atom-cli-1" in result.stdout


def test_cli_rebuild_index_removes_stale_entries_and_rebuilds_fts(temp_wiki_root) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor
    from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-rebuild-keep",
            topic="indexing",
            problem_cluster="rebuild",
            summary="Keep indexed page.",
            content="# Keep\n\nCurrent manifest-backed content.",
            source_refs=[],
        ),
    )
    with (temp_wiki_root / "retrieval_index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "wiki_id": "personal-1",
                    "doc_id": "raw-rebuild-stale",
                    "page_type": "raw",
                    "topic": "indexing",
                    "problem_cluster": "rebuild",
                    "content": "stale orphan content",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    fts = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    fts.upsert("raw-rebuild-stale", {"wiki_id": "personal-1", "doc_id": "raw-rebuild-stale", "content": "stale orphan content"})

    result = CliRunner().invoke(
        app,
        ["rebuild-index", "--workspace", str(temp_wiki_root), "--registry", "tests/fixtures/registry.yaml"],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "removed_count=1" in result.stdout
    assert "rebuilt_count=1" in result.stdout
    retrieval_index = (temp_wiki_root / "retrieval_index.jsonl").read_text(encoding="utf-8")
    assert "raw-rebuild-keep" in retrieval_index
    assert "raw-rebuild-stale" not in retrieval_index
    assert fts.search("stale orphan", top_k=5) == []
    assert [hit.doc_id for hit in fts.search("Current manifest-backed", top_k=5)] == ["raw-rebuild-keep"]

    second = CliRunner().invoke(
        app,
        ["rebuild-index", "--workspace", str(temp_wiki_root), "--registry", "tests/fixtures/registry.yaml"],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert second.exit_code == 0
    assert "removed_count=0" in second.stdout
    assert "rebuilt_count=1" in second.stdout


def test_cli_rebuild_index_with_embedding_flag_forwards_include_embedding(monkeypatch, temp_wiki_root) -> None:
    import agent_wiki.transports.cli.app as cli_app

    captured: dict[str, object] = {}

    class FakeMaintenanceService:
        def rebuild_index(self, wiki, include_embedding=False):
            captured["include_embedding"] = include_embedding
            return {"removed_count": 0, "rebuilt_count": 0, "embedded_count": 0}

    monkeypatch.setattr(cli_app, "MaintenanceService", lambda: FakeMaintenanceService())

    result = CliRunner().invoke(
        app,
        [
            "rebuild-index",
            "--include-embedding",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert captured["include_embedding"] is True


def test_cli_eval_retrieval_outputs_json_report(monkeypatch, tmp_path) -> None:
    import agent_wiki.transports.cli.app as cli_app

    eval_file = tmp_path / "retrieval_queries.jsonl"
    eval_file.write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeEvalRetrievalService:
        def run(self, wiki, actor, eval_file, k, page_types=None):
            captured["workspace_path"] = wiki.workspace_path
            captured["actor_id"] = actor.actor_id
            captured["eval_file"] = str(eval_file)
            captured["k"] = k
            captured["page_types"] = page_types
            return {
                "query_count": 0,
                "k": k,
                "metrics": {
                    "strict_recall_at_k": 0.0,
                    "loose_recall_at_k": 0.0,
                    "must_not_violation_at_k": 0.0,
                    "mrr": 0.0,
                    "compiled_hit_ratio": 0.0,
                },
                "queries": [],
            }

    monkeypatch.setattr(cli_app, "EvalRetrievalService", lambda: FakeEvalRetrievalService())

    result = CliRunner().invoke(
        app,
        [
            "eval-retrieval",
            "--eval-file",
            str(eval_file),
            "--k",
            "7",
            "--workspace",
            "/tmp",
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["query_count"] == 0
    assert json.loads(result.stdout)["metrics"]["strict_recall_at_k"] == 0.0
    assert json.loads(result.stdout)["metrics"]["loose_recall_at_k"] == 0.0
    assert json.loads(result.stdout)["metrics"]["must_not_violation_at_k"] == 0.0
    assert captured == {
        "workspace_path": "/tmp",
        "actor_id": "claude-code",
        "eval_file": str(eval_file),
        "k": 7,
        "page_types": None,
    }


def test_cli_eval_alias_outputs_json_report(monkeypatch, tmp_path) -> None:
    import agent_wiki.transports.cli.app as cli_app

    eval_file = tmp_path / "retrieval_queries.jsonl"
    eval_file.write_text("", encoding="utf-8")

    class FakeEvalRetrievalService:
        def run(self, wiki, actor, eval_file, k, page_types=None):
            return {
                "query_count": 0,
                "k": k,
                "metrics": {
                    "strict_recall_at_k": 1.0,
                    "loose_recall_at_k": 1.0,
                    "must_not_violation_at_k": 0.0,
                    "mrr": 1.0,
                    "compiled_hit_ratio": 1.0,
                },
                "queries": [],
            }

    monkeypatch.setattr(cli_app, "EvalRetrievalService", lambda: FakeEvalRetrievalService())

    result = CliRunner().invoke(
        app,
        [
            "eval",
            "--eval-file",
            str(eval_file),
            "--workspace",
            "/tmp",
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["metrics"]["strict_recall_at_k"] == 1.0


def test_cli_review_relations_reclassifies_review_item(temp_wiki_root) -> None:
    graph_path = temp_wiki_root / "knowledge_graph.jsonl"
    graph_path.write_text(
        json.dumps(
            {
                "subject": "Huawei",
                "relation": "competes_with",
                "object": "Apple",
                "source_doc_id": "raw-relation-cli",
                "confidence_label": "AMBIGUOUS",
                "confidence_score": 0.4,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (temp_wiki_root / "review_queue.jsonl").write_text(
        json.dumps(
            {
                "item_id": "relation_review:Huawei:Apple:competes_with",
                "item_type": "relation_review",
                "status": "open",
                "content_state": {"subject": "Huawei", "object": "Apple", "relation": "competes_with"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "review-relations",
            "--action",
            "reclassify",
            "--confidence",
            "INFERRED",
            "--item-id",
            "relation_review:Huawei:Apple:competes_with",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "status=resolved" in result.stdout
    relation = json.loads(graph_path.read_text(encoding="utf-8").strip())
    queue_item = json.loads((temp_wiki_root / "review_queue.jsonl").read_text(encoding="utf-8").strip())
    assert relation["confidence_label"] == "INFERRED"
    assert relation["confidence_score"] == 0.7
    assert queue_item["status"] == "resolved"


def test_cli_compile_prepare_command_prints_source_refs(temp_wiki_root) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-cli-prepare-1",
            topic="agents",
            problem_cluster="memory",
            content="# CLI Prepare\n\nClaim: Agents need working memory.",
            source_refs=[],
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "compile-prepare",
            "--topic",
            "agents",
            "--problem-cluster",
            "memory",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "proposed_doc_id=atom-agents-memory-0001" in result.stdout
    assert "source_ref=personal-1:raw-cli-prepare-1" in result.stdout


def test_cli_review_queue_consume_command_assigns_item(temp_wiki_root) -> None:
    from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository

    ReviewQueueRepository(temp_wiki_root).append(
        {"item_id": "compile_suggestion:cli:consume", "item_type": "compile_suggestion", "status": "open"}
    )

    result = CliRunner().invoke(
        app,
        [
            "review-queue-consume",
            "--item-type",
            "compile_suggestion",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "item_id=compile_suggestion:cli:consume" in result.stdout
    assert ReviewQueueRepository(temp_wiki_root).find("compile_suggestion:cli:consume")["assigned_to"] == "claude-code"


def test_cli_lint_command(temp_wiki_root) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["lint", "--workspace", str(temp_wiki_root), "--registry", "tests/fixtures/registry.yaml"], env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"})

    assert result.exit_code == 0
    assert "ok" in result.stdout.lower() or "no issues" in result.stdout.lower()


def test_cli_sync_status_command(temp_wiki_root) -> None:
    from pathlib import Path
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-cli-sync-status-1",
            topic="testing",
            problem_cluster="cluster-cli-sync-status",
            content="# Raw cli sync status",
            source_refs=[],
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["sync", "status", "--workspace", str(temp_wiki_root), "--registry", "tests/fixtures/registry.yaml"],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "pages/raw-cli-sync-status-1.md" in result.stdout


def test_cli_sync_push_view_command(temp_wiki_root) -> None:
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "cli-sync-push-1.md").write_text("# CLI Sync Push", encoding="utf-8")
    external_dir = temp_wiki_root / "cli-sync-vault"
    external_dir.mkdir(exist_ok=True)

    registry_path = temp_wiki_root.parent / "registry-cli-sync.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["external_views"] = [
        {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
    ]
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "sync",
            "push-view",
            "--doc-id",
            "cli-sync-push-1",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            str(registry_path),
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert (external_dir / "cli-sync-push-1.md").exists()
    assert "push-view" in result.stdout


def test_cli_feedback_command_records_feedback(temp_wiki_root) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "feedback",
            "--query-id",
            "q-cli-feedback-1",
            "--missing-evidence",
            "--rewrite-target",
            "atom-cli-feedback-1",
            "--notes",
            "needs stronger proof",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "created_review_item=True" in result.stdout
    assert (temp_wiki_root / "feedback_outcomes.jsonl").exists()
    assert (temp_wiki_root / "review_queue.jsonl").exists()


def test_cli_weekly_review_command_prints_summary(temp_wiki_root) -> None:
    from pathlib import Path
    from agent_wiki.application.feedback import FeedbackInput, FeedbackService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    FeedbackService().record(
        wiki,
        FeedbackInput(
            query_id="q-cli-weekly-1",
            approved=False,
            missing_evidence=True,
            rewrite_targets=["atom-cli-weekly-1"],
            notes="backfill evidence",
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["weekly-review", "--workspace", str(temp_wiki_root), "--registry", "tests/fixtures/registry.yaml"],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "feedback_issue" in result.stdout
    assert "backfill evidence" in result.stdout


def test_cli_approvals_propose_and_approve_commands(tmp_path) -> None:
    from pathlib import Path
    from shutil import copytree

    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    personal_root = tmp_path / "cli-approval-personal"
    shared_root = tmp_path / "cli-approval-shared"
    copytree(Path("tests/fixtures/sample_wiki"), personal_root)
    copytree(Path("tests/fixtures/shared_wiki"), shared_root)

    registry_path = tmp_path / "registry-cli-approvals.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry_multi.yaml").read_text())
    registry_data["wikis"][0]["workspace_path"] = str(personal_root)
    registry_data["wikis"][1]["workspace_path"] = str(shared_root)
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    personal_wiki = RegistryLoader().load(registry_path).wikis[0]
    CaptureRawService().execute(
        wiki=personal_wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-cli-approval-1",
            topic="testing",
            problem_cluster="cluster-cli-approval",
            content="# Raw cli approval",
            source_refs=[],
        ),
    )

    runner = CliRunner()
    propose = runner.invoke(
        app,
        [
            "approvals",
            "propose",
            "--wiki-id",
            "shared-1",
            "--proposal-id",
            "proposal-cli-1",
            "--doc-id",
            "principle-cli-1",
            "--page-type",
            "principle",
            "--topic",
            "testing",
            "--problem-cluster",
            "cluster-cli-approval",
            "--content",
            "# Principle cli\n\nApproved through CLI.",
            "--source-ref",
            "personal-1:raw-cli-approval-1",
            "--registry",
            str(registry_path),
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert propose.exit_code == 0
    assert "status=proposed" in propose.stdout

    approve = runner.invoke(
        app,
        [
            "approvals",
            "approve",
            "--wiki-id",
            "shared-1",
            "--proposal-id",
            "proposal-cli-1",
            "--registry",
            str(registry_path),
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert approve.exit_code == 0
    assert "status=approved" in approve.stdout
    assert (shared_root / "pages" / "principle-cli-1.md").exists()


def test_cli_approvals_reject_command_is_explicitly_unimplemented() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "approvals",
            "reject",
            "--wiki-id",
            "shared-1",
            "--proposal-id",
            "proposal-cli-1",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 1
    assert "not implemented" in result.stdout.lower()


def test_cli_maintain_runs_orchestrator_and_prints_quality_report(temp_wiki_root) -> None:
    from pathlib import Path
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # Seed 3 raw pages in same cluster → triggers compile_suggestion
    for i in range(3):
        CaptureRawService().execute(
            wiki=wiki, actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-cli-maint-{i}", topic="logging",
                problem_cluster="cluster-cli-maint",
                content=f"# Raw cli maint {i}", source_refs=[],
            ),
        )

    runner = CliRunner()
    result = runner.invoke(app, ["maintain", "--workspace", str(temp_wiki_root), "--registry", "tests/fixtures/registry.yaml"], env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"})

    assert result.exit_code == 0
    # Maintenance summary output
    assert "compile_suggestions" in result.stdout
    # Quality report output
    assert "raw_count" in result.stdout
    assert "hit_rate" in result.stdout
    assert "compile_rate" in result.stdout
    assert "orphan_count" in result.stdout


def test_cli_query_uses_registry_option_and_identity_env(temp_wiki_root) -> None:
    from pathlib import Path
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    registry_path = temp_wiki_root.parent / "registry-cli.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["permissions"].append(
        {
            "actor_type": "agent",
            "actor_id": "codex",
            "allowed_operations": ["query", "capture_raw", "compile_update", "lint"],
            "max_gate": "B",
            "allowed_page_types": ["raw", "atom", "synthesis"],
        }
    )
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    wiki = RegistryLoader().load(registry_path).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="codex", transport="cli")

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-cli-env-1",
            topic="testing",
            problem_cluster="cluster-cli-env",
            content="# Raw cli env",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-cli-env-1",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-cli-env",
            content="# Atom cli env\n\nCLI env identity results.",
            source_refs=["personal-1:raw-cli-env-1"],
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "query",
            "CLI env identity results",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            str(registry_path),
        ],
        env={
            "AGENT_WIKI_ACTOR_TYPE": "agent",
            "AGENT_WIKI_ACTOR_ID": "codex",
        },
    )

    assert result.exit_code == 0
    assert "atom-cli-env-1" in result.stdout


def test_cli_compile_update_maps_permission_error_to_structured_output(temp_wiki_root) -> None:
    from pathlib import Path
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    registry_path = temp_wiki_root.parent / "registry-cli-permission.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["permissions"].append(
        {
            "actor_type": "agent",
            "actor_id": "codex",
            "allowed_operations": ["query", "capture_raw"],
            "max_gate": "A",
            "allowed_page_types": ["raw"],
        }
    )
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    wiki = RegistryLoader().load(registry_path).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    CaptureRawService().execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="codex", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-cli-perm-1",
            topic="testing",
            problem_cluster="cluster-cli-perm",
            content="# Raw cli permission",
            source_refs=[],
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "compile-update",
            "atom-cli-perm-1",
            "--page-type",
            "atom",
            "--topic",
            "testing",
            "--problem-cluster",
            "cluster-cli-perm",
            "--content",
            "# Atom denied",
            "--source-refs",
            "personal-1:raw-cli-perm-1",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            str(registry_path),
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "codex"},
    )

    assert result.exit_code == 1
    assert '"type":"permission_denied"' in result.stdout



def test_cli_health_command_reports_registry_and_tool_surface(temp_wiki_root) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "health",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "status=ok" in result.stdout
    assert "wiki_count=1" in result.stdout
    assert "tool_count=6" in result.stdout
    assert "actor_type=agent" in result.stdout
    assert "actor_id=claude-code" in result.stdout


def test_cli_health_reports_index_consistency_anomaly(temp_wiki_root) -> None:
    import json

    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "raw-health-index.md").write_text("# Raw Health Index", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        json.dumps(
            {
                "wiki_id": "personal-1",
                "doc_id": "raw-health-index",
                "page_type": "raw",
                "topic": "ops",
                "problem_cluster": "health",
                "summary": "health index",
                "canonical_uri": "pages/raw-health-index.md",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (temp_wiki_root / "retrieval_index.jsonl").write_text("", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["health", "--workspace", str(temp_wiki_root), "--registry", "tests/fixtures/registry.yaml"],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "index_consistency=fail" in result.stdout
    assert "rebuild retrieval indexes" in result.stdout.lower()


def test_cli_compile_execute_prints_packet_json(temp_wiki_root) -> None:
    import json
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

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
                doc_id=f"raw-execute-{index}",
                topic="imaging-os",
                problem_cluster="cluster-execute",
                content=f"# Raw execute {index}\n\nClaim: execute {index}.",
                source_refs=[],
            ),
        )

    result = CliRunner().invoke(
        app,
        [
            "compile-execute",
            "--limit",
            "1",
            "--priority-filter",
            "P0",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    packet = json.loads(result.stdout.strip().splitlines()[-1])
    assert packet["item_type"] == "compile_suggestion"
    assert packet["priority_label"] == "P0"
    assert packet["prepare"]["agent_objective"] == "create_retrieval_ready_atom"


def test_cli_compile_execute_applies_input_file_and_resolves_queue_item(temp_wiki_root) -> None:
    import json
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

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
                doc_id=f"raw-execute-input-{index}",
                topic="imaging-os",
                problem_cluster="cluster-execute-input",
                content=f"# Raw execute input {index}\n\nClaim: compile execution {index}.",
                source_refs=[],
            ),
        )

    packet_result = CliRunner().invoke(
        app,
        [
            "compile-execute",
            "--limit",
            "1",
            "--priority-filter",
            "P0",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )
    packet = json.loads(packet_result.stdout.strip().splitlines()[-1])
    payload = {
        "item_id": packet["item_id"],
        "doc_id": packet["prepare"]["proposed_doc_id"],
        "page_type": packet["prepare"]["proposed_page_type"],
        "topic": packet["prepare"]["topic"],
        "problem_cluster": packet["prepare"]["problem_cluster"],
        "source_refs": packet["prepare"]["source_refs"],
        "summary": "Compile execution summary.",
        "confidence": "medium",
        "content": "# Atom compiled\n\n## Claims\n- raw-execute-input-0\n- raw-execute-input-1\n- raw-execute-input-2\n\n## Evidence\n- compile execution.",
    }
    input_path = temp_wiki_root / "compiled.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "compile-execute",
            "--input-file",
            str(input_path),
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "status=committed" in result.stdout
    assert "queue_status=resolved" in result.stdout
    assert (temp_wiki_root / "pages" / f"{payload['doc_id']}.md").exists()


def test_cli_compile_execute_apply_runs_single_command_pipeline(monkeypatch, temp_wiki_root) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.application.compile_suggest import CompileSuggestService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor
    from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "purpose.md").write_text("# Purpose\n\n## Topics\n\n- imaging-os\n", encoding="utf-8")
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    for index in range(3):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-cli-apply-{index}",
                topic="imaging-os",
                problem_cluster="cli-apply",
                content=f"# Raw CLI Apply {index}\n\nClaim: apply {index}.",
                source_refs=[],
            ),
        )
    CompileSuggestService().detect_and_enqueue(wiki)

    class FakeApplyService:
        def generate(self, wiki, prepare):
            self.last_structured_output = CompileStructuredOutput(
                content="# CLI Generated Atom\n\n## Claims\n- raw-cli-apply-0\n- raw-cli-apply-1\n- raw-cli-apply-2\n\n## Evidence\n- generated through --apply.",
                summary="CLI generated summary.",
                confidence="medium",
            )
            return self.last_structured_output.content

    monkeypatch.setattr("agent_wiki.application.compile_execute.CompileApplyService", lambda: FakeApplyService())

    result = CliRunner().invoke(
        app,
        [
            "compile-execute",
            "--apply",
            "--limit",
            "1",
            "--priority-filter",
            "P0",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "status=committed" in result.stdout
    assert "queue_status=resolved" in result.stdout
    assert "doc_id=atom-imaging-os-cli-apply-0001" in result.stdout
    item = ReviewQueueRepository(temp_wiki_root).find("compile_suggestion:imaging-os:cli-apply:0001")
    assert item["status"] == "resolved"
    assert (temp_wiki_root / "pages" / "atom-imaging-os-cli-apply-0001.md").read_text(encoding="utf-8").startswith("# CLI Generated Atom")


def test_cli_compile_execute_apply_prints_fallback_priority(monkeypatch, temp_wiki_root) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.application.compile_suggest import CompileSuggestService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "purpose.md").write_text("# Purpose\n\n## Topics\n\n- imaging-os\n", encoding="utf-8")
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    for index in range(3):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-cli-apply-fallback-{index}",
                topic="misc-topic",
                problem_cluster="cli-apply-fallback",
                content=f"# Raw CLI Apply Fallback {index}\n\nClaim: fallback {index}.",
                source_refs=[],
            ),
        )
    CompileSuggestService().detect_and_enqueue(wiki)

    class FakeApplyService:
        def generate(self, wiki, prepare):
            self.last_structured_output = CompileStructuredOutput(
                content="# CLI Fallback Atom\n\n## Claims\n- raw-cli-apply-fallback-0\n- raw-cli-apply-fallback-1\n- raw-cli-apply-fallback-2\n\n## Evidence\n- generated through fallback.",
                summary="CLI fallback summary.",
                confidence="medium",
            )
            return self.last_structured_output.content

    monkeypatch.setattr("agent_wiki.application.compile_execute.CompileApplyService", lambda: FakeApplyService())

    result = CliRunner().invoke(
        app,
        [
            "compile-execute",
            "--apply",
            "--limit",
            "1",
            "--priority-filter",
            "P0",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "status=committed" in result.stdout
    assert "fallback_priority=P1" in result.stdout


def test_cli_maintain_auto_tune_flag_forwards_to_service(monkeypatch, temp_wiki_root) -> None:
    import agent_wiki.transports.cli.app as cli_app

    captured: dict[str, object] = {}

    class FakeMaintenanceService:
        def run(self, wiki, auto_tune=False):
            captured["workspace_path"] = wiki.workspace_path
            captured["auto_tune"] = auto_tune
            return {"status": "ok"}

    monkeypatch.setattr(cli_app, "MaintenanceService", lambda: FakeMaintenanceService())

    result = CliRunner().invoke(
        app,
        [
            "maintain",
            "--auto-tune",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert captured["workspace_path"] == str(temp_wiki_root)
    assert captured["auto_tune"] is True
