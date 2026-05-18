from pathlib import Path

from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.transports.mcp.server import MCPServer, build_fastmcp_server, run_stdio_server
import yaml


def test_mcp_server_lists_expected_tools() -> None:
    server = MCPServer()
    tools = server.list_tools()

    tool_names = {tool["name"] for tool in tools}
    assert tool_names == {
        "wiki.query",
        "wiki.capture_raw",
        "wiki.compile_prepare",
        "wiki.compile_update",
        "wiki.lint",
        "wiki.sync",
    }


def test_mcp_compile_prepare_tool_returns_raw_batch(temp_wiki_root: Path) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    for index in range(2):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-mcp-prepare-{index}",
                topic="compile",
                problem_cluster="prepare",
                content=f"# MCP Prepare {index}",
                source_refs=[],
            ),
        )

    result = MCPServer(registry_path="tests/fixtures/registry.yaml").invoke(
        "wiki.compile_prepare",
        {"wiki_id": "personal-1", "topic": "compile", "problem_cluster": "prepare"},
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    assert result["topic"] == "compile"
    assert result["problem_cluster"] == "prepare"
    assert result["source_refs"] == ["personal-1:raw-mcp-prepare-0", "personal-1:raw-mcp-prepare-1"]
    assert result["items"][0]["doc_id"] == "raw-mcp-prepare-0"


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


def test_mcp_lint_tool_returns_structured_issue_payload(temp_wiki_root: Path) -> None:
    server = MCPServer(registry_path="tests/fixtures/registry.yaml")

    result = server.invoke(
        "wiki.lint",
        {"wiki_id": "personal-1"},
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    assert set(result) == {"ok", "issues", "issue_count"}
    assert result["ok"] is True
    assert result["issues"] == []
    assert result["issue_count"] == 0


def test_mcp_sync_tool_accepts_doc_ids(temp_wiki_root: Path) -> None:
    server = MCPServer(registry_path="tests/fixtures/registry.yaml")

    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "atom-1.md").write_text("# Atom 1", encoding="utf-8")
    (pages_dir / "atom-2.md").write_text("# Atom 2", encoding="utf-8")
    external_dir = temp_wiki_root / "mcp-sync-vault"
    external_dir.mkdir(exist_ok=True)

    registry_path = temp_wiki_root.parent / "registry-mcp-sync.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["external_views"] = [
        {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
    ]
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    server = MCPServer(registry_path=str(registry_path))
    result = server.invoke(
        "wiki.sync",
        {"wiki_id": "personal-1", "mode": "push-view", "doc_ids": ["atom-1"]},
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    assert result["mode"] == "push-view"
    assert isinstance(result["changed_files"], list)
    assert (external_dir / "atom-1.md").exists()
    assert not (external_dir / "atom-2.md").exists()


def test_mcp_sync_tool_supports_status_mode(temp_wiki_root: Path) -> None:
    server = MCPServer(registry_path="tests/fixtures/registry.yaml")

    result = server.invoke(
        "wiki.sync",
        {"wiki_id": "personal-1", "mode": "status"},
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    assert result["mode"] == "status"
    assert "changed_files" in result
    assert isinstance(result["changed_files"], list)


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


def test_mcp_compile_update_maps_permission_error_to_structured_response(temp_wiki_root: Path) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.domain.contracts import ResolvedActor

    registry_path = temp_wiki_root.parent / "registry-mcp-permission.yaml"
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
        actor=ResolvedActor(actor_type="agent", actor_id="codex", transport="mcp"),
        data=CaptureRawInput(
            doc_id="raw-mcp-perm-1",
            topic="testing",
            problem_cluster="cluster-mcp-perm",
            content="# Raw mcp permission",
            source_refs=[],
        ),
    )

    server = MCPServer(registry_path=str(registry_path))
    result = server.invoke(
        "wiki.compile_update",
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-mcp-perm-1",
            "page_type": "atom",
            "topic": "testing",
            "problem_cluster": "cluster-mcp-perm",
            "content": "# Atom denied",
            "source_refs": ["personal-1:raw-mcp-perm-1"],
        },
        session_metadata={"actor_type": "agent", "actor_id": "codex"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    assert result["error"]["type"] == "permission_denied"


def test_build_fastmcp_server_registers_agent_wiki_tools() -> None:
    import asyncio

    app = build_fastmcp_server(registry_path="tests/fixtures/registry.yaml")

    tools = {tool.name for tool in asyncio.run(app.list_tools())}

    assert app.name == "agent-wiki"
    assert tools == {
        "wiki.query",
        "wiki.capture_raw",
        "wiki.compile_prepare",
        "wiki.compile_update",
        "wiki.lint",
        "wiki.sync",
    }


def test_run_stdio_server_uses_stdio_transport(monkeypatch) -> None:
    captured = {}

    class FakeFastMCP:
        def run(self, transport: str = "stdio") -> None:
            captured["transport"] = transport

    monkeypatch.setattr("agent_wiki.transports.mcp.server.build_fastmcp_server", lambda **_: FakeFastMCP())

    run_stdio_server(registry_path="tests/fixtures/registry.yaml")

    assert captured["transport"] == "stdio"



def test_mcp_metadata_from_context_does_not_read_env(monkeypatch) -> None:
    from agent_wiki.transports.mcp.server import _metadata_from_context

    monkeypatch.setenv("AGENT_WIKI_ACTOR_TYPE", "agent")
    monkeypatch.setenv("AGENT_WIKI_ACTOR_ID", "hermes")

    assert _metadata_from_context(None) == {}


def test_mcp_registry_fallback_logs_warning_when_env_missing(monkeypatch, caplog) -> None:
    import logging

    monkeypatch.delenv("AGENT_WIKI_ACTOR_TYPE", raising=False)
    monkeypatch.delenv("AGENT_WIKI_ACTOR_ID", raising=False)
    server = MCPServer(registry_path="tests/fixtures/registry.yaml")

    with caplog.at_level(logging.WARNING):
        resolved = server.resolve_identity(request_metadata={}, session_metadata={})

    assert resolved.actor_type == "agent"
    assert resolved.actor_id == "hermes"
    assert "registry fallback" in caplog.text


def test_mcp_identity_errors_when_no_env_no_metadata_no_registry_defaults(monkeypatch, temp_wiki_root: Path) -> None:
    monkeypatch.delenv("AGENT_WIKI_ACTOR_TYPE", raising=False)
    monkeypatch.delenv("AGENT_WIKI_ACTOR_ID", raising=False)
    registry_path = temp_wiki_root.parent / "registry-no-permissions.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text(encoding="utf-8"))
    registry_data["wikis"][0]["permissions"] = []
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    server = MCPServer(registry_path=str(registry_path))

    try:
        server.resolve_identity(request_metadata={}, session_metadata={})
    except Exception as error:
        assert error.__class__.__name__ == "IdentityResolutionError"
    else:
        raise AssertionError("expected IdentityResolutionError")


def test_fastmcp_capture_raw_tool_does_not_reference_compile_fields(temp_wiki_root: Path) -> None:
    import asyncio
    import yaml

    from agent_wiki.transports.mcp.server import build_fastmcp_server

    registry_path = temp_wiki_root.parent / "registry-fastmcp-capture.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["workspace_path"] = str(temp_wiki_root)
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")
    app = build_fastmcp_server(registry_path=str(registry_path))

    result = asyncio.run(app.call_tool(
        "wiki.capture_raw",
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-fastmcp-cap-1",
            "topic": "testing",
            "problem_cluster": "cluster-fastmcp-cap",
            "content": "# Raw FastMCP cap",
            "source_refs": [],
        },
    ))

    payload = result[1] if isinstance(result, tuple) else result

    assert payload["status"] == "committed"
    assert (temp_wiki_root / "pages" / "raw-fastmcp-cap-1.md").exists()
