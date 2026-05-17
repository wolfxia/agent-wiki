from pydantic import BaseModel, Field
from mcp.server.fastmcp import Context, FastMCP

from agent_wiki.transports.mcp.dispatcher import MCPDispatcher


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


class MutationToolResult(BaseModel):
    status: str | None = None
    doc_id: str | None = None
    page_path: str | None = None
    reason: str | None = None
    error: ToolErrorResult | None = None


class LintToolResult(BaseModel):
    ok: bool | None = None
    issues: list[str] = Field(default_factory=list)
    issue_count: int = 0
    error: ToolErrorResult | None = None


class SyncToolResult(BaseModel):
    mode: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    error: ToolErrorResult | None = None


def _metadata_from_context(ctx: Context | None) -> dict[str, str]:
    if ctx is None:
        return _env_fallback()

    metadata: dict[str, str] = {}
    client_id = getattr(ctx, "client_id", None)
    if client_id:
        metadata["client_id"] = client_id

    request_context = getattr(ctx, "request_context", None)
    request_meta = getattr(request_context, "meta", None) if request_context is not None else None
    if request_meta is not None:
        actor_type = getattr(request_meta, "actor_type", None)
        actor_id = getattr(request_meta, "actor_id", None)
        if actor_type:
            metadata["actor_type"] = actor_type
        if actor_id:
            metadata["actor_id"] = actor_id

    # Merge env defaults for any missing identity fields
    env_meta = _env_fallback()
    for key in ("actor_type", "actor_id"):
        if key not in metadata and key in env_meta:
            metadata[key] = env_meta[key]

    return metadata


def _env_fallback() -> dict[str, str]:
    """Read default actor identity from environment variables."""
    import os

    result: dict[str, str] = {}
    actor_type = os.environ.get("AGENT_WIKI_ACTOR_TYPE")
    actor_id = os.environ.get("AGENT_WIKI_ACTOR_ID")
    if actor_type:
        result["actor_type"] = actor_type
    if actor_id:
        result["actor_id"] = actor_id
    return result


def build_fastmcp_server(registry_path: str | None = None) -> FastMCP:
    dispatcher = MCPDispatcher(registry_path=registry_path)
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
            dispatcher.dispatch(
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
            dispatcher.dispatch(
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
        ctx: Context | None = None,
    ) -> MutationToolResult:
        return MutationToolResult.model_validate(
            dispatcher.dispatch(
                tool_name="wiki.compile_update",
                params={
                    "wiki_id": wiki_id,
                    "doc_id": doc_id,
                    "page_type": page_type,
                    "topic": topic,
                    "problem_cluster": problem_cluster,
                    "content": content,
                    "source_refs": source_refs or [],
                },
                session_metadata=_metadata_from_context(ctx),
            )
        )

    @server.tool(name="wiki.lint", structured_output=True)
    def lint_tool(wiki_id: str, ctx: Context | None = None) -> LintToolResult:
        return LintToolResult.model_validate(
            dispatcher.dispatch(
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
            dispatcher.dispatch(
                tool_name="wiki.sync",
                params={"wiki_id": wiki_id, "mode": mode, "doc_ids": doc_ids},
                session_metadata=_metadata_from_context(ctx),
            )
        )

    return server


def run_stdio_server(registry_path: str | None = None) -> None:
    build_fastmcp_server(registry_path=registry_path).run(transport="stdio")


class MCPServer:
    def __init__(self, registry_path: str | None = None) -> None:
        self._dispatcher = MCPDispatcher(registry_path=registry_path)

    def list_tools(self) -> list[dict]:
        return [
            {"name": "wiki.query", "description": "Query the agent wiki"},
            {"name": "wiki.capture_raw", "description": "Capture a raw page"},
            {"name": "wiki.compile_update", "description": "Compile a truth-zone page"},
            {"name": "wiki.lint", "description": "Lint wiki state and indexes"},
            {"name": "wiki.sync", "description": "Run explicit wiki sync operations"},
        ]

    def invoke(
        self,
        tool_name: str,
        params: dict,
        request_metadata: dict | None = None,
        session_metadata: dict | None = None,
        wiki_workspace_overrides: dict[str, str] | None = None,
    ) -> dict:
        return self._dispatcher.dispatch(
            tool_name=tool_name,
            params=params,
            request_metadata=request_metadata,
            session_metadata=session_metadata,
            wiki_workspace_overrides=wiki_workspace_overrides,
        )

    def resolve_identity(self, request_metadata: dict, session_metadata: dict):
        return self._dispatcher.resolve_identity(request_metadata, session_metadata)
