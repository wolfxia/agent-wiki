from pathlib import Path

from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.extensions import MCPToolContext, MCPToolSpec
from agent_wiki.transports.mcp.server import MCPServer


def test_mcp_server_invokes_extra_tool_with_identity_and_permission_context(temp_wiki_root: Path) -> None:
    seen: dict = {}

    def handler(ctx: MCPToolContext) -> dict:
        decision = ctx.check_permission(operation="capture_raw", page_type="raw")
        seen["actor_id"] = ctx.actor.actor_id
        seen["wiki_id"] = ctx.wiki.wiki_id
        seen["params"] = ctx.params
        return {"allowed": decision.allowed, "required_gate": decision.required_gate}

    tool = MCPToolSpec(
        name="ka.ingest_document",
        description="Ingest a downstream document",
        handler=handler,
        required_operation="capture_raw",
        required_page_type="raw",
    )

    server = MCPServer(registry_path="tests/fixtures/registry.yaml", extra_tools=[tool])

    assert "ka.ingest_document" in {item["name"] for item in server.list_tools()}

    result = server.invoke(
        "ka.ingest_document",
        {"wiki_id": "personal-1", "doc_id": "doc-1"},
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    assert result == {"allowed": True, "required_gate": "A"}
    assert seen == {
        "actor_id": "claude-code",
        "wiki_id": "personal-1",
        "params": {"wiki_id": "personal-1", "doc_id": "doc-1"},
    }


def test_mcp_server_rejects_duplicate_extra_tool_name() -> None:
    def handler(ctx: MCPToolContext) -> dict:
        return {}

    tool = MCPToolSpec(name="wiki.query", description="Duplicate", handler=handler)

    try:
        MCPServer(registry_path="tests/fixtures/registry.yaml", extra_tools=[tool])
    except ValueError as error:
        assert "duplicate MCP tool name" in str(error)
    else:
        raise AssertionError("expected duplicate tool failure")


def test_extra_tool_uses_same_registry_identity_fallback(temp_wiki_root: Path) -> None:
    def handler(ctx: MCPToolContext) -> dict:
        return {"actor_id": ctx.actor.actor_id, "wiki_id": ctx.wiki.wiki_id}

    tool = MCPToolSpec(name="ka.identity_probe", description="Probe identity", handler=handler)
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]

    server = MCPServer(registry_path="tests/fixtures/registry.yaml", extra_tools=[tool])
    result = server.invoke(
        "ka.identity_probe",
        {"wiki_id": wiki.wiki_id},
        wiki_workspace_overrides={wiki.wiki_id: str(temp_wiki_root)},
    )

    assert result == {"actor_id": "hermes", "wiki_id": "personal-1"}
