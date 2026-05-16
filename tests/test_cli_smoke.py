from typer.testing import CliRunner

from agent_wiki.transports.cli.app import app


def test_cli_help_renders() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Agent Wiki CLI" in result.stdout
