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
