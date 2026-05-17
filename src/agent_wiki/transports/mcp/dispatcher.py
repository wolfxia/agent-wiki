from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.linting import LintService
from agent_wiki.application.query import QueryService
from agent_wiki.application.sync import SyncInput, SyncService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.models import (
    CaptureRawInput,
    CompileUpdateInput,
    IdentityContext,
    QueryInput,
)
from agent_wiki.infrastructure.identity.resolver import IdentityResolver
from agent_wiki.settings import DEFAULT_REGISTRY_PATH
from agent_wiki.transports.errors import map_exception


class MCPDispatcher:
    def __init__(self, registry_path: str | None = None) -> None:
        self._registry_path = Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH

    def dispatch(
        self,
        tool_name: str,
        params: dict,
        request_metadata: dict | None = None,
        session_metadata: dict | None = None,
        wiki_workspace_overrides: dict[str, str] | None = None,
    ) -> dict:
        try:
            handler = {
                "wiki.query": self._tool_query,
                "wiki.capture_raw": self._tool_capture_raw,
                "wiki.compile_update": self._tool_compile_update,
                "wiki.lint": self._tool_lint,
                "wiki.sync": self._tool_sync,
            }.get(tool_name)
            if handler is None:
                raise ValueError(f"unknown tool: {tool_name}")
            actor = self.resolve_identity(request_metadata or {}, session_metadata or {})
            wiki = self._resolve_wiki(params["wiki_id"], wiki_workspace_overrides or {})
            return handler(params, wiki, actor)
        except Exception as exc:
            mapped = map_exception(exc)
            payload: dict = {"error": mapped.as_dict()}
            if tool_name in {"wiki.capture_raw", "wiki.compile_update"}:
                payload["status"] = "denied" if mapped.type in {"permission_denied", "gate_blocked"} else "error"
                payload["reason"] = mapped.message
            return payload

    def resolve_identity(self, request_metadata: dict, session_metadata: dict):
        return IdentityResolver().resolve(
            IdentityContext(
                transport="mcp",
                metadata={**request_metadata, **session_metadata},
            )
        )

    def _resolve_wiki(self, wiki_id: str, workspace_overrides: dict[str, str]):
        registry = RegistryLoader().load(self._registry_path)
        wiki = next((candidate for candidate in registry.wikis if candidate.wiki_id == wiki_id), None)
        if wiki is None:
            raise ValueError(f"unknown wiki_id: {wiki_id}")
        override = workspace_overrides.get(wiki_id)
        if override:
            wiki = wiki.model_copy(update={"workspace_path": override})
        return wiki

    def _tool_query(self, params: dict, wiki, actor) -> dict:
        result = QueryService().execute(
            wiki=wiki,
            actor=actor,
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

    def _tool_capture_raw(self, params: dict, wiki, actor) -> dict:
        result = CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=params["doc_id"],
                topic=params["topic"],
                problem_cluster=params["problem_cluster"],
                content=params["content"],
                source_refs=params.get("source_refs", []),
            ),
        )
        return {"status": result.status, "doc_id": result.doc_id, "page_path": result.page_path}

    def _tool_compile_update(self, params: dict, wiki, actor) -> dict:
        result = CompileUpdateService().apply(
            wiki=wiki,
            actor=actor,
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

    def _tool_lint(self, params: dict, wiki, actor) -> dict:
        result = LintService().run(wiki)
        return {"ok": result.ok, "issues": result.issues, "issue_count": len(result.issues)}

    def _tool_sync(self, params: dict, wiki, actor) -> dict:
        result = SyncService().execute(
            wiki,
            actor,
            SyncInput(mode=params["mode"], doc_ids=params.get("doc_ids")),
        )
        return {"mode": result.mode, "changed_files": result.changed_files}
