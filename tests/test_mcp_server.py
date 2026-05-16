from pathlib import Path

from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.transports.mcp.server import MCPServer
import yaml


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

    server = MCPServer(registry_path="tests/fixtures/registry.yaml")
    result = server.invoke(
        "wiki.query",
        {"wiki_id": "personal-1", "query": "MCP server delegation"},
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    assert result["hit_count"] >= 1
    assert any(h["doc_id"] == "atom-mcp-1" for h in result["hits"])


def test_mcp_capture_tool_delegates_to_capture_service(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    server = MCPServer(registry_path="tests/fixtures/registry.yaml")
    result = server.invoke(
        "wiki.capture_raw",
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-mcp-cap-1",
            "topic": "testing",
            "problem_cluster": "cluster-mcp-cap",
            "content": "# Raw mcp cap",
            "source_refs": [],
        },
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
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

    server = MCPServer(registry_path="tests/fixtures/registry.yaml")
    result = server.invoke(
        "wiki.compile_update",
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-mcp-comp-1",
            "page_type": "atom",
            "topic": "testing",
            "problem_cluster": "cluster-mcp-comp",
            "content": "# Atom mcp comp",
            "source_refs": ["personal-1:raw-mcp-comp-1"],
        },
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
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



def test_mcp_invoke_uses_session_identity_not_caller_actor(temp_wiki_root: Path) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.domain.contracts import ResolvedActor

    registry_path = temp_wiki_root.parent / "registry-mcp.yaml"
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
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp"),
        data=CaptureRawInput(
            doc_id="raw-mcp-auth-1",
            topic="testing",
            problem_cluster="cluster-mcp-auth",
            content="# Raw mcp auth",
            source_refs=[],
        ),
    )

    server = MCPServer(registry_path=str(registry_path))
    result = server.invoke(
        "wiki.compile_update",
        {
            "wiki_id": "personal-1",
            "actor": {"actor_type": "agent", "actor_id": "claude-code"},
            "doc_id": "atom-mcp-auth-1",
            "page_type": "atom",
            "topic": "testing",
            "problem_cluster": "cluster-mcp-auth",
            "content": "# Atom mcp auth",
            "source_refs": ["personal-1:raw-mcp-auth-1"],
        },
        request_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        session_metadata={"actor_type": "agent", "actor_id": "codex"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    assert result["status"] == "denied"
    assert not (temp_wiki_root / "pages" / "atom-mcp-auth-1.md").exists()
