from agent_wiki.application.capture_raw import CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.query import QueryService
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import (
    CaptureRawInput,
    CompileUpdateInput,
    IdentityContext,
    QueryInput,
)
from agent_wiki.infrastructure.identity.resolver import IdentityResolver


class MCPServer:
    def __init__(self) -> None:
        self._tools = {
            "wiki.query": self._tool_query,
            "wiki.capture_raw": self._tool_capture_raw,
            "wiki.compile_update": self._tool_compile_update,
        }

    def list_tools(self) -> list[dict]:
        return [
            {"name": "wiki.query", "description": "Query the agent wiki"},
            {"name": "wiki.capture_raw", "description": "Capture a raw page"},
            {"name": "wiki.compile_update", "description": "Compile a truth-zone page"},
        ]

    def invoke(self, tool_name: str, params: dict) -> dict:
        handler = self._tools.get(tool_name)
        if handler is None:
            raise ValueError(f"unknown tool: {tool_name}")
        return handler(params)

    def resolve_identity(self, request_metadata: dict, session_metadata: dict) -> ResolvedActor:
        # Session metadata wins; request fields are ignored
        return IdentityResolver().resolve(
            IdentityContext(
                transport="mcp",
                metadata={**request_metadata, **session_metadata},
            )
        )

    def _tool_query(self, params: dict) -> dict:
        result = QueryService().execute(
            wiki=params["wiki"],
            actor=params["actor"],
            data=QueryInput(
                query=params["query"],
                include_pending=params.get("include_pending", False),
                max_sensitivity=params.get("max_sensitivity"),
            ),
        )
        return {
            "query_type": result.query_type,
            "l1_answer": result.l1_answer,
            "l2_context": result.l2_context,
            "l3_proof": result.l3_proof,
            "hits": [{"doc_id": h.doc_id, "wiki_id": h.wiki_id, "score": h.score} for h in result.hits],
            "hit_count": result.hit_count,
            "miss_signal": result.miss_signal,
        }

    def _tool_capture_raw(self, params: dict) -> dict:
        result = CaptureRawService().execute(
            wiki=params["wiki"],
            actor=params["actor"],
            data=CaptureRawInput(
                doc_id=params["doc_id"],
                topic=params["topic"],
                problem_cluster=params["problem_cluster"],
                content=params["content"],
                source_refs=params.get("source_refs", []),
            ),
        )
        return {"status": result.status, "doc_id": result.doc_id, "page_path": result.page_path}

    def _tool_compile_update(self, params: dict) -> dict:
        result = CompileUpdateService().apply(
            wiki=params["wiki"],
            actor=params["actor"],
            data=CompileUpdateInput(
                doc_id=params["doc_id"],
                page_type=params["page_type"],
                topic=params["topic"],
                problem_cluster=params["problem_cluster"],
                content=params["content"],
                source_refs=params.get("source_refs", []),
            ),
        )
        return {"status": result.status, "doc_id": result.doc_id, "page_path": result.page_path}
