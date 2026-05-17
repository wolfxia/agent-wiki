from pathlib import Path


def test_hermes_deployment_doc_includes_mcp_server_example() -> None:
    doc = Path("docs/deployment/hermes-mcp.md").read_text(encoding="utf-8")

    assert "Hermes MCP Deployment" in doc
    assert '"mcpServers"' in doc
    assert '"agent-wiki"' in doc
    assert '"aw-agent"' in doc
    assert '"serve"' in doc
    assert "wiki.query" in doc
