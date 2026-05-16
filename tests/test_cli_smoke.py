from typer.testing import CliRunner

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
    result = runner.invoke(app, ["query", "CLI query results", "--workspace", str(temp_wiki_root)])

    assert result.exit_code == 0
    assert "atom-cli-1" in result.stdout


def test_cli_lint_command(temp_wiki_root) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["lint", "--workspace", str(temp_wiki_root)])

    assert result.exit_code == 0
    assert "ok" in result.stdout.lower() or "no issues" in result.stdout.lower()


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
    result = runner.invoke(app, ["maintain", "--workspace", str(temp_wiki_root)])

    assert result.exit_code == 0
    # Maintenance summary output
    assert "compile_suggestions" in result.stdout
    # Quality report output
    assert "raw_count" in result.stdout
    assert "hit_rate" in result.stdout
    assert "compile_rate" in result.stdout
    assert "orphan_count" in result.stdout
