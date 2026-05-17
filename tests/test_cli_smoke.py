from pathlib import Path

from typer.testing import CliRunner
import yaml

from agent_wiki.transports.cli.app import app


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
    assert (temp_wiki_root / "query_outcomes.jsonl").exists()
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
