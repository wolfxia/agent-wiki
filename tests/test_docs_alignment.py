from pathlib import Path

from typer.testing import CliRunner

from agent_wiki.transports.cli.app import app
from agent_wiki.transports.mcp.server import MCPServer


def test_authoritative_knowledge_system_spec_exists_and_supersedes_old_retrieval_spec() -> None:
    unified = Path("docs/specs/knowledge-system-architecture.md")
    retrieval = Path("docs/specs/retrieval-architecture.md")

    assert unified.exists()
    unified_text = unified.read_text(encoding="utf-8")
    assert "Authoritative architecture spec" in unified_text
    assert "Supersedes: `docs/specs/retrieval-architecture.md`" in unified_text

    retrieval_text = retrieval.read_text(encoding="utf-8")
    assert "Superseded by `docs/specs/knowledge-system-architecture.md`" in retrieval_text


def test_readme_avoids_hardcoded_test_count_and_points_to_authoritative_spec() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "151 tests" not in readme
    assert "151 passing tests" not in readme
    assert "Chinese-aware tokenization" not in readme
    assert "docs/specs/knowledge-system-architecture.md" in readme


def test_mcp_tool_surface_matches_documented_phase1_workflow() -> None:
    tools = MCPServer().list_tools()

    assert [tool["name"] for tool in tools] == [
        "wiki.query",
        "wiki.get_doc",
        "wiki.inbound_refs",
        "wiki.capture_raw",
        "wiki.compile_prepare",
        "wiki.compile_update",
        "wiki.lint",
        "wiki.sync",
    ]


def test_cli_help_surface_covers_documented_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in [
        "info",
        "health",
        "serve",
        "query",
        "capture-raw",
        "compile-update",
        "compile-prepare",
        "compile-execute",
        "review-queue-consume",
        "lint",
        "sync",
        "feedback",
        "weekly-review",
        "dream-cycle",
        "approvals",
        "maintain",
    ]:
        assert command in result.stdout

    sync_result = runner.invoke(app, ["sync", "--help"])
    assert sync_result.exit_code == 0
    for command in ["status", "pull-view", "push-view"]:
        assert command in sync_result.stdout

    approvals_result = runner.invoke(app, ["approvals", "--help"])
    assert approvals_result.exit_code == 0
    for command in ["propose", "approve", "reject"]:
        assert command in approvals_result.stdout



def test_docs_alignment_keeps_key_claims_in_sync() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "151 tests" not in readme
    assert "Chinese-aware tokenization" not in readme
    assert "docs/specs/knowledge-system-architecture.md" in readme

    assert [tool["name"] for tool in MCPServer().list_tools()] == [
        "wiki.query",
        "wiki.get_doc",
        "wiki.inbound_refs",
        "wiki.capture_raw",
        "wiki.compile_prepare",
        "wiki.compile_update",
        "wiki.lint",
        "wiki.sync",
    ]

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.stdout
    assert "health" in result.stdout
