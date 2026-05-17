from pathlib import Path

from typer.testing import CliRunner

from agent_wiki.transports.cli.app import app


def test_health_selfcheck_reports_registry_anomaly(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry-empty.yaml"
    registry_path.write_text(
        "version: 1\ndefault_route_policy: local_first\nwikis: []\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["health", "--registry", str(registry_path)])

    assert result.exit_code == 1
    assert '"type":"invalid_input"' in result.stdout
    assert "registry must contain at least one wiki" in result.stdout
