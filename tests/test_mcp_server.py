from pathlib import Path

from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.transports.mcp.server import MCPServer


def test_mcp_server_lists_expected_tools() -> None:
    server = MCPServer()
    tools = server.list_tools()

    tool_names = {tool["name"] for tool in tools}
    assert "wiki.query" in tool_names
    assert "wiki.capture_raw" in tool_names
    assert "wiki.compile_update" in tool_names


def test_mcp_query_tool_delegates_to_query_service(temp_wiki_root: Path) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    CaptureRawService().execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-mcp-1", topic="testing", problem_cluster="cluster-mcp",
            content="# Raw mcp", source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-mcp-1", page_type="atom", topic="testing",
            problem_cluster="cluster-mcp",
            content="# Atom mcp\n\nMCP server delegation.",
            source_refs=["personal-1:raw-mcp-1"],
        ),
    )

    server = MCPServer()
    result = server.invoke(
        "wiki.query",
        {"wiki": wiki, "actor": actor, "query": "MCP server delegation"},
    )

    assert result["hit_count"] >= 1
    assert any(h["doc_id"] == "atom-mcp-1" for h in result["hits"])


def test_mcp_capture_tool_delegates_to_capture_service(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    server = MCPServer()
    result = server.invoke(
        "wiki.capture_raw",
        {
            "wiki": wiki, "actor": actor,
            "doc_id": "raw-mcp-cap-1",
            "topic": "testing",
            "problem_cluster": "cluster-mcp-cap",
            "content": "# Raw mcp cap",
            "source_refs": [],
        },
    )

    assert result["status"] == "committed"
    assert (temp_wiki_root / "pages" / "raw-mcp-cap-1.md").exists()


def test_mcp_compile_tool_delegates_to_compile_service(temp_wiki_root: Path) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    CaptureRawService().execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-mcp-comp-1", topic="testing",
            problem_cluster="cluster-mcp-comp",
            content="# Raw mcp comp", source_refs=[],
        ),
    )

    server = MCPServer()
    result = server.invoke(
        "wiki.compile_update",
        {
            "wiki": wiki, "actor": actor,
            "doc_id": "atom-mcp-comp-1",
            "page_type": "atom",
            "topic": "testing",
            "problem_cluster": "cluster-mcp-comp",
            "content": "# Atom mcp comp",
            "source_refs": ["personal-1:raw-mcp-comp-1"],
        },
    )

    assert result["status"] == "committed"
    assert (temp_wiki_root / "pages" / "atom-mcp-comp-1.md").exists()


def test_mcp_resolves_identity_from_session_metadata() -> None:
    """MCP transport should not trust request-supplied actor fields."""
    server = MCPServer()
    resolved = server.resolve_identity(
        request_metadata={"actor_id": "spoofed-id", "actor_type": "human"},
        session_metadata={"actor_id": "trusted-agent", "actor_type": "agent"},
    )

    # Session metadata wins over request fields
    assert resolved.actor_id == "trusted-agent"
    assert resolved.actor_type == "agent"
    assert resolved.transport == "mcp"
