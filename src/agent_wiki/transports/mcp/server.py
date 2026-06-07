from __future__ import annotations
from pydantic import BaseModel, Field
from typing import TYPE_CHECKING, Any

from agent_wiki.extensions.mcp import MCPToolSpec

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context, FastMCP
else:
    Context = Any


class ToolErrorResult(BaseModel):
    type: str
    message: str


class QueryToolResult(BaseModel):
    query_type: str | None = None
    l1_answer: str | None = None
    l2_context: list[dict] = Field(default_factory=list)
    l3_proof: list[dict] = Field(default_factory=list)
    hits: list[dict] = Field(default_factory=list)
    hit_count: int = 0
    miss_signal: bool = False
    error: ToolErrorResult | None = None


class GetDocToolResult(BaseModel):
    wiki_id: str | None = None
    doc_id: str | None = None
    page_type: str | None = None
    canonical_uri: str | None = None
    metadata: dict = Field(default_factory=dict)
    content: str | None = None
    error: ToolErrorResult | None = None


class InboundRefsToolResult(BaseModel):
    wiki_id: str | None = None
    doc_id: str | None = None
    ref_count: int = 0
    refs: list[dict] = Field(default_factory=list)
    error: ToolErrorResult | None = None


class MutationToolResult(BaseModel):
    status: str | None = None
    doc_id: str | None = None
    page_path: str | None = None
    reason: str | None = None
    error: ToolErrorResult | None = None


class CompilePrepareToolResult(BaseModel):
    topic: str | None = None
    problem_cluster: str | None = None
    sub_cluster_id: str | None = None
    proposed_page_type: str | None = None
    proposed_doc_id: str | None = None
    agent_objective: str | None = None
    total_raw_count: int = 0
    source_refs: list[str] = Field(default_factory=list)
    relationship_hints: list[dict] = Field(default_factory=list)
    contradiction_markers: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    error: ToolErrorResult | None = None


class LintToolResult(BaseModel):
    ok: bool | None = None
    issues: list[str] = Field(default_factory=list)
    issue_count: int = 0
    metrics: dict = Field(default_factory=dict)
    error: ToolErrorResult | None = None


class SyncToolResult(BaseModel):
    mode: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    error: ToolErrorResult | None = None


def _metadata_from_context(ctx: Context | None) -> dict[str, str]:
    if ctx is None:
        return {}

    metadata: dict[str, str] = {}
    try:
        client_id = getattr(ctx, "client_id", None)
    except ValueError:
        client_id = None
    if client_id:
        metadata["client_id"] = client_id

    try:
        request_context = getattr(ctx, "request_context", None)
    except ValueError:
        request_context = None
    request_meta = getattr(request_context, "meta", None) if request_context is not None else None
    if request_meta is not None:
        actor_type = getattr(request_meta, "actor_type", None)
        actor_id = getattr(request_meta, "actor_id", None)
        if actor_type:
            metadata["actor_type"] = actor_type
        if actor_id:
            metadata["actor_id"] = actor_id

    return metadata


_BUILTIN_TOOLS = {
    "wiki.query": "Query the agent wiki",
    "wiki.get_doc": "Read an exact committed wiki document",
    "wiki.inbound_refs": "List exact inbound source_refs and wikilinks for a document",
    "wiki.capture_raw": "Capture a raw page",
    "wiki.compile_prepare": "Prepare raw evidence for agent-driven compilation",
    "wiki.compile_update": "Compile a truth-zone page",
    "wiki.lint": "Lint wiki state and indexes",
    "wiki.sync": "Run explicit wiki sync operations",
}


def _validate_extra_tools(extra_tools: list[MCPToolSpec] | None) -> list[MCPToolSpec]:
    tools = list(extra_tools or [])
    seen = set(_BUILTIN_TOOLS)
    for tool in tools:
        if tool.name in seen:
            raise ValueError(f"duplicate MCP tool name: {tool.name}")
        seen.add(tool.name)
    return tools


def _dispatcher_cls():
    from agent_wiki.transports.mcp.dispatcher import MCPDispatcher

    return MCPDispatcher


def build_fastmcp_server(registry_path: str | None = None, extra_tools: list[MCPToolSpec] | None = None) -> "FastMCP":
    from mcp.server.fastmcp import FastMCP

    extra_tools = _validate_extra_tools(extra_tools)
    dispatcher = None

    def _dispatcher():
        nonlocal dispatcher
        if dispatcher is None:
            dispatcher = _dispatcher_cls()(registry_path=registry_path, extra_tools=extra_tools)
        return dispatcher

    server = FastMCP(name="agent-wiki")

    @server.tool(name="wiki.query", structured_output=True)
    def query_tool(
        wiki_id: str,
        query: str,
        include_pending: bool = False,
        max_sensitivity: str | None = None,
        ctx: Context | None = None,
    ) -> QueryToolResult:
        return QueryToolResult.model_validate(
            _dispatcher().dispatch(
                tool_name="wiki.query",
                params={
                    "wiki_id": wiki_id,
                    "query": query,
                    "include_pending": include_pending,
                    "max_sensitivity": max_sensitivity,
                },
                session_metadata=_metadata_from_context(ctx),
            )
        )

    @server.tool(name="wiki.get_doc", structured_output=True)
    def get_doc_tool(
        wiki_id: str,
        doc_id: str,
        ctx: Context | None = None,
    ) -> GetDocToolResult:
        return GetDocToolResult.model_validate(
            _dispatcher().dispatch(
                tool_name="wiki.get_doc",
                params={"wiki_id": wiki_id, "doc_id": doc_id},
                session_metadata=_metadata_from_context(ctx),
            )
        )

    @server.tool(name="wiki.inbound_refs", structured_output=True)
    def inbound_refs_tool(
        wiki_id: str,
        doc_id: str,
        ctx: Context | None = None,
    ) -> InboundRefsToolResult:
        return InboundRefsToolResult.model_validate(
            _dispatcher().dispatch(
                tool_name="wiki.inbound_refs",
                params={"wiki_id": wiki_id, "doc_id": doc_id},
                session_metadata=_metadata_from_context(ctx),
            )
        )

    @server.tool(name="wiki.capture_raw", structured_output=True)
    def capture_raw_tool(
        wiki_id: str,
        doc_id: str,
        topic: str,
        problem_cluster: str,
        content: str,
        source_refs: list[str] | None = None,
        ctx: Context | None = None,
    ) -> MutationToolResult:
        return MutationToolResult.model_validate(
            _dispatcher().dispatch(
                tool_name="wiki.capture_raw",
                params={
                    "wiki_id": wiki_id,
                    "doc_id": doc_id,
                    "topic": topic,
                    "problem_cluster": problem_cluster,
                    "content": content,
                    "source_refs": source_refs or [],
                },
                session_metadata=_metadata_from_context(ctx),
            )
        )

    @server.tool(name="wiki.compile_update", structured_output=True)
    def compile_update_tool(
        wiki_id: str,
        doc_id: str,
        page_type: str,
        topic: str,
        problem_cluster: str,
        content: str,
        source_refs: list[str] | None = None,
        summary: str | None = None,
        aliases: list[str] | None = None,
        confidence: str | None = None,
        contested: bool = False,
        wikilinks: list[str] | None = None,
        sensitivity: str | None = None,
        ctx: Context | None = None,
    ) -> MutationToolResult:
        return MutationToolResult.model_validate(
            _dispatcher().dispatch(
                tool_name="wiki.compile_update",
                params={
                    "wiki_id": wiki_id,
                    "doc_id": doc_id,
                    "page_type": page_type,
                    "topic": topic,
                    "problem_cluster": problem_cluster,
                    "content": content,
                    "source_refs": source_refs or [],
                    "summary": summary,
                    "aliases": aliases or [],
                    "confidence": confidence,
                    "contested": contested,
                    "wikilinks": wikilinks or [],
                    "sensitivity": sensitivity,
                },
                session_metadata=_metadata_from_context(ctx),
            )
        )

    @server.tool(name="wiki.compile_prepare", structured_output=True)
    def compile_prepare_tool(
        wiki_id: str,
        topic: str,
        problem_cluster: str,
        doc_ids: list[str] | None = None,
        max_items: int = 8,
        sub_cluster_index: int = 1,
        ctx: Context | None = None,
    ) -> CompilePrepareToolResult:
        return CompilePrepareToolResult.model_validate(
            _dispatcher().dispatch(
                tool_name="wiki.compile_prepare",
                params={
                    "wiki_id": wiki_id,
                    "topic": topic,
                    "problem_cluster": problem_cluster,
                    "doc_ids": doc_ids,
                    "max_items": max_items,
                    "sub_cluster_index": sub_cluster_index,
                },
                session_metadata=_metadata_from_context(ctx),
            )
        )

    @server.tool(name="wiki.lint", structured_output=True)
    def lint_tool(wiki_id: str, ctx: Context | None = None) -> LintToolResult:
        return LintToolResult.model_validate(
            _dispatcher().dispatch(
                tool_name="wiki.lint",
                params={"wiki_id": wiki_id},
                session_metadata=_metadata_from_context(ctx),
            )
        )

    @server.tool(name="wiki.sync", structured_output=True)
    def sync_tool(
        wiki_id: str,
        mode: str,
        doc_ids: list[str] | None = None,
        ctx: Context | None = None,
    ) -> SyncToolResult:
        return SyncToolResult.model_validate(
            _dispatcher().dispatch(
                tool_name="wiki.sync",
                params={"wiki_id": wiki_id, "mode": mode, "doc_ids": doc_ids},
                session_metadata=_metadata_from_context(ctx),
            )
        )

    def _make_extra_tool(spec: MCPToolSpec):
        def _extra_tool(ctx: Context | None = None, **params) -> dict:
            return _dispatcher().dispatch(
                tool_name=spec.name,
                params=params,
                session_metadata=_metadata_from_context(ctx),
            )
        return _extra_tool

    for spec in extra_tools:
        server.tool(name=spec.name, description=spec.description)(_make_extra_tool(spec))
        # FastMCP generates a broken schema from **params; replace with the
        # explicit schema from MCPToolSpec, or a permissive fallback.
        registered = server._tool_manager._tools[spec.name]
        if spec.input_schema is not None:
            registered.parameters = spec.input_schema
        else:
            registered.parameters = {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            }

    return server


def run_stdio_server(registry_path: str | None = None) -> None:
    build_fastmcp_server(registry_path=registry_path).run(transport="stdio")


class MCPServer:
    def __init__(self, registry_path: str | None = None, extra_tools: list[MCPToolSpec] | None = None) -> None:
        self._registry_path = registry_path
        self._extra_tools = _validate_extra_tools(extra_tools)
        self._dispatcher = None

    def _get_dispatcher(self):
        if self._dispatcher is None:
            self._dispatcher = _dispatcher_cls()(registry_path=self._registry_path, extra_tools=self._extra_tools)
        return self._dispatcher

    def list_tools(self) -> list[dict]:
        return [
            *[{"name": name, "description": description} for name, description in _BUILTIN_TOOLS.items()],
            *[{"name": tool.name, "description": tool.description} for tool in self._extra_tools],
        ]

    def invoke(
        self,
        tool_name: str,
        params: dict,
        request_metadata: dict | None = None,
        session_metadata: dict | None = None,
        wiki_workspace_overrides: dict[str, str] | None = None,
    ) -> dict:
        return self._get_dispatcher().dispatch(
            tool_name=tool_name,
            params=params,
            request_metadata=request_metadata,
            session_metadata=session_metadata,
            wiki_workspace_overrides=wiki_workspace_overrides,
        )

    def resolve_identity(self, request_metadata: dict, session_metadata: dict):
        return self._get_dispatcher().resolve_identity(request_metadata, session_metadata)
