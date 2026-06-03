import asyncio
import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.transports.mcp.server import MCPServer, build_fastmcp_server


def test_fastmcp_compile_update_schema_exposes_retrieval_ready_fields() -> None:
    app = build_fastmcp_server(registry_path="tests/fixtures/registry.yaml")

    tools = {tool.name: tool for tool in asyncio.run(app.list_tools())}
    schema = tools["wiki.compile_update"].inputSchema

    for field in ["summary", "aliases", "confidence", "contested", "wikilinks", "sensitivity"]:
        assert field in schema["properties"]


def test_mcp_compile_update_persists_retrieval_ready_fields_and_query_uses_summary(temp_wiki_root: Path) -> None:
    registry_path = temp_wiki_root.parent / "registry-mcp-compile-schema.yaml"
    registry_data = json.loads(json.dumps(__import__("yaml").safe_load(Path("tests/fixtures/registry.yaml").read_text())))
    registry_path.write_text(__import__("yaml").safe_dump(registry_data, sort_keys=False), encoding="utf-8")
    wiki = RegistryLoader().load(registry_path).wikis[0].model_copy(update={"workspace_path": str(temp_wiki_root)})
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-mcp-schema-1",
            topic="deployment",
            problem_cluster="canary",
            content="# Raw schema",
            source_refs=[],
        ),
    )

    result = MCPServer(registry_path=str(registry_path)).invoke(
        "wiki.compile_update",
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-mcp-schema-1",
            "page_type": "atom",
            "topic": "deployment",
            "problem_cluster": "canary",
            "summary": "Canary deployment requires staged rollout.",
            "aliases": ["灰度发布"],
            "confidence": "medium",
            "contested": True,
            "wikilinks": ["[[raw-mcp-schema-1]]"],
            "sensitivity": "internal",
            "content": "# Canary deployment\n\nDetailed staged rollout body.",
            "source_refs": ["personal-1:raw-mcp-schema-1"],
        },
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    manifest_entry = next(
        json.loads(line)
        for line in (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8").splitlines()
        if '"doc_id": "atom-mcp-schema-1"' in line
    )
    query_result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="canary deployment"),
    )

    assert result["status"] == "committed"
    assert manifest_entry["summary"] == "Canary deployment requires staged rollout."
    assert manifest_entry["aliases"] == ["灰度发布"]
    assert manifest_entry["confidence"] == "medium"
    assert manifest_entry["contested"] is True
    assert manifest_entry["wikilinks"] == ["[[raw-mcp-schema-1]]"]
    assert manifest_entry["sensitivity"] == "internal"
    assert query_result.hits[0].doc_id == "atom-mcp-schema-1"
    assert query_result.l1_answer == "Canary deployment requires staged rollout."


def test_mcp_compile_update_aliases_are_queryable(temp_wiki_root: Path) -> None:
    registry_path = temp_wiki_root.parent / "registry-mcp-compile-alias.yaml"
    registry_data = json.loads(json.dumps(__import__("yaml").safe_load(Path("tests/fixtures/registry.yaml").read_text())))
    registry_path.write_text(__import__("yaml").safe_dump(registry_data, sort_keys=False), encoding="utf-8")
    wiki = RegistryLoader().load(registry_path).wikis[0].model_copy(update={"workspace_path": str(temp_wiki_root)})
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-mcp-alias-1",
            topic="agent-os",
            problem_cluster="protocol",
            content="# Raw alias",
            source_refs=[],
        ),
    )

    MCPServer(registry_path=str(registry_path)).invoke(
        "wiki.compile_update",
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-mcp-alias-1",
            "page_type": "atom",
            "topic": "agent-os",
            "problem_cluster": "protocol",
            "summary": "Agent OS protocol note.",
            "aliases": ["shared context sidecar"],
            "confidence": "medium",
            "content": "# Agent OS protocol\n\nGeneral MCP note.",
            "source_refs": ["personal-1:raw-mcp-alias-1"],
        },
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )

    query_result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="shared context sidecar"),
    )

    assert query_result.hits[0].doc_id == "atom-mcp-alias-1"
