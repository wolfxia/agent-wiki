from pathlib import Path

import yaml

from agent_wiki.transports.mcp.server import MCPServer


def test_mcp_tool_surface_supports_all_five_tools_in_one_flow(temp_wiki_root: Path) -> None:
    external_dir = temp_wiki_root / "combo-mcp-vault"
    external_dir.mkdir(exist_ok=True)

    registry_path = temp_wiki_root.parent / "registry-combo-mcp.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["external_views"] = [
        {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
    ]
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    server = MCPServer(registry_path=str(registry_path))
    session = {"actor_type": "agent", "actor_id": "claude-code"}
    overrides = {"personal-1": str(temp_wiki_root)}

    capture_result = server.invoke(
        "wiki.capture_raw",
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-mcp-combo-1",
            "topic": "combo",
            "problem_cluster": "mcp-combo",
            "content": "# Raw mcp combo",
            "source_refs": [],
        },
        session_metadata=session,
        wiki_workspace_overrides=overrides,
    )

    compile_result = server.invoke(
        "wiki.compile_update",
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-mcp-combo-1",
            "page_type": "atom",
            "topic": "combo",
            "problem_cluster": "mcp-combo",
            "content": "# Atom mcp combo\n\nMCP combo tool surface.",
            "source_refs": ["personal-1:raw-mcp-combo-1"],
        },
        session_metadata=session,
        wiki_workspace_overrides=overrides,
    )

    query_result = server.invoke(
        "wiki.query",
        {"wiki_id": "personal-1", "query": "MCP combo tool surface"},
        session_metadata=session,
        wiki_workspace_overrides=overrides,
    )
    lint_result = server.invoke(
        "wiki.lint",
        {"wiki_id": "personal-1"},
        session_metadata=session,
        wiki_workspace_overrides=overrides,
    )
    sync_result = server.invoke(
        "wiki.sync",
        {"wiki_id": "personal-1", "mode": "push-view", "doc_ids": ["atom-mcp-combo-1"]},
        session_metadata=session,
        wiki_workspace_overrides=overrides,
    )

    assert capture_result["status"] == "committed"
    assert compile_result["status"] == "committed"
    assert query_result["hit_count"] >= 1
    assert query_result["hits"][0]["doc_id"] == "atom-mcp-combo-1"
    assert lint_result["ok"] is True
    assert sync_result["mode"] == "push-view"
    assert (external_dir / "atom-mcp-combo-1.md").exists()
