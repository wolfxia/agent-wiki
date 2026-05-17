from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent_wiki.application.approvals import ApprovalService
from agent_wiki.application.capture_raw import CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.feedback import FeedbackInput, FeedbackService
from agent_wiki.application.linting import LintService
from agent_wiki.application.sync import SyncInput, SyncService
from agent_wiki.application.weekly_review import WeeklyReviewService
from agent_wiki.application.query import QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CaptureRawInput, IdentityContext, QueryInput, ProposalInput
from agent_wiki.infrastructure.identity.resolver import IdentityResolver
from agent_wiki.settings import DEFAULT_REGISTRY_PATH
from agent_wiki.transports.errors import error_payload, map_exception


class QueryRequest(BaseModel):
    query: str
    include_pending: bool = False
    max_sensitivity: str | None = None


class CaptureRequest(BaseModel):
    doc_id: str
    topic: str
    problem_cluster: str
    content: str
    source_refs: list[str] = []


class CompileUpdateRequest(BaseModel):
    doc_id: str
    page_type: str
    topic: str
    problem_cluster: str
    content: str
    source_refs: list[str] = []


class SyncRequest(BaseModel):
    mode: str
    doc_ids: list[str] | None = None


class FeedbackRequest(BaseModel):
    query_id: str
    approved: bool
    missing_evidence: bool
    rewrite_targets: list[str] = []
    notes: str = ""


class ProposalRequest(BaseModel):
    wiki_id: str
    proposal_id: str
    doc_id: str
    page_type: str
    topic: str
    problem_cluster: str
    content: str
    source_refs: list[str] = []


class ApproveRequest(BaseModel):
    wiki_id: str
    proposal_id: str


from agent_wiki.transports.errors import map_exception


def create_app(
    wiki_workspace: str | None = None,
    registry_path: str | None = None,
    token_identities: dict[str, dict[str, str]] | None = None,
) -> FastAPI:
    app = FastAPI(title="agent-wiki")

    @app.exception_handler(Exception)
    async def _map_domain_exceptions(request: Any, exc: Exception):  # type: ignore[arg-type]
        from fastapi.responses import JSONResponse

        if isinstance(exc, HTTPException):
            raise exc
        mapped = map_exception(exc)
        return JSONResponse(
            status_code=mapped.http_status,
            content={"error": {"type": mapped.type, "message": mapped.message}},
        )

    state: dict[str, Any] = {
        "wiki_workspace": wiki_workspace,
        "registry_path": Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH,
        "token_identities": token_identities or {},
    }

    def _resolve_wiki():
        registry = RegistryLoader().load(state["registry_path"])
        wiki = registry.wikis[0]
        if state["wiki_workspace"]:
            wiki = wiki.model_copy(update={"workspace_path": state["wiki_workspace"]})
        return wiki

    def _resolve_wiki_by_id(wiki_id: str):
        registry = RegistryLoader().load(state["registry_path"])
        wiki = next((candidate for candidate in registry.wikis if candidate.wiki_id == wiki_id), None)
        if wiki is None:
            raise HTTPException(status_code=404, detail=f"unknown wiki_id: {wiki_id}")
        if state["wiki_workspace"]:
            wiki = wiki.model_copy(update={"workspace_path": state["wiki_workspace"]})
        return wiki

    def _rest_call(action):
        try:
            return action()
        except Exception as exc:
            mapped = map_exception(exc)
            return JSONResponse(status_code=mapped.status_code, content=error_payload(exc))

    def _resolve_actor(authorization: str | None) -> ResolvedActor:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        identity = state["token_identities"].get(token)
        if identity is None:
            raise HTTPException(status_code=401, detail="unknown token")
        return IdentityResolver().resolve(
            IdentityContext(
                transport="rest",
                metadata={
                    "actor_type": identity.get("actor_type", "agent"),
                    "actor_id": identity.get("actor_id", "unknown"),
                },
            )
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "agent-wiki"}

    @app.post("/query")
    def query(request: QueryRequest, authorization: str | None = Header(default=None)) -> dict:
        return _rest_call(lambda: _query_impl(request, authorization))

    def _query_impl(request: QueryRequest, authorization: str | None) -> dict:
        wiki = _resolve_wiki()
        actor = _resolve_actor(authorization)
        result = QueryService().execute(
            wiki=wiki,
            actor=actor,
            data=QueryInput(
                query=request.query,
                include_pending=request.include_pending,
                max_sensitivity=request.max_sensitivity,
            ),
        )
        return {
            "query_type": result.query_type,
            "l1_answer": result.l1_answer,
            "l2_context": result.l2_context,
            "l3_proof": result.l3_proof,
            "hit_count": result.hit_count,
            "miss_signal": result.miss_signal,
            "hits": [{"doc_id": h.doc_id, "wiki_id": h.wiki_id, "score": h.score} for h in result.hits],
        }

    @app.post("/capture-raw")
    def capture_raw(request: CaptureRequest, authorization: str | None = Header(default=None)) -> dict:
        return _rest_call(lambda: _capture_raw_impl(request, authorization))

    def _capture_raw_impl(request: CaptureRequest, authorization: str | None) -> dict:
        wiki = _resolve_wiki()
        actor = _resolve_actor(authorization)
        result = CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=request.doc_id,
                topic=request.topic,
                problem_cluster=request.problem_cluster,
                content=request.content,
                source_refs=request.source_refs,
            ),
        )
        return {"status": result.status, "doc_id": result.doc_id, "page_path": result.page_path}

    @app.post("/compile-update")
    def compile_update(request: CompileUpdateRequest, authorization: str | None = Header(default=None)) -> dict:
        return _rest_call(lambda: _compile_update_impl(request, authorization))

    def _compile_update_impl(request: CompileUpdateRequest, authorization: str | None) -> dict:
        wiki = _resolve_wiki()
        actor = _resolve_actor(authorization)
        result = CompileUpdateService().apply(
            wiki=wiki,
            actor=actor,
            data=CompileUpdateInput(
                doc_id=request.doc_id,
                page_type=request.page_type,
                topic=request.topic,
                problem_cluster=request.problem_cluster,
                content=request.content,
                source_refs=request.source_refs,
            ),
        )
        return {"status": result.status, "doc_id": result.doc_id, "page_path": result.page_path}

    @app.get("/lint")
    def lint(authorization: str | None = Header(default=None)) -> dict:
        return _rest_call(lambda: _lint_impl(authorization))

    def _lint_impl(authorization: str | None) -> dict:
        wiki = _resolve_wiki()
        _resolve_actor(authorization)
        result = LintService().run(wiki)
        return {"ok": result.ok, "issues": result.issues}

    @app.post("/sync")
    def sync(request: SyncRequest, authorization: str | None = Header(default=None)) -> dict:
        return _rest_call(lambda: _sync_impl(request, authorization))

    def _sync_impl(request: SyncRequest, authorization: str | None) -> dict:
        wiki = _resolve_wiki()
        actor = _resolve_actor(authorization)
        result = SyncService().execute(wiki, actor, SyncInput(mode=request.mode, doc_ids=request.doc_ids))
        return {"mode": result.mode, "changed_files": result.changed_files}

    @app.post("/feedback")
    def feedback(request: FeedbackRequest, authorization: str | None = Header(default=None)) -> dict:
        return _rest_call(lambda: _feedback_impl(request, authorization))

    def _feedback_impl(request: FeedbackRequest, authorization: str | None) -> dict:
        wiki = _resolve_wiki()
        _resolve_actor(authorization)
        result = FeedbackService().record(
            wiki,
            FeedbackInput(
                query_id=request.query_id,
                approved=request.approved,
                missing_evidence=request.missing_evidence,
                rewrite_targets=request.rewrite_targets,
                notes=request.notes,
            ),
        )
        return {"created_review_item": result.created_review_item}

    @app.get("/weekly-review")
    def weekly_review(authorization: str | None = Header(default=None)) -> dict:
        return _rest_call(lambda: _weekly_review_impl(authorization))

    def _weekly_review_impl(authorization: str | None) -> dict:
        wiki = _resolve_wiki()
        _resolve_actor(authorization)
        result = WeeklyReviewService().generate(wiki)
        return {"summary": result.summary, "suggested_actions": result.suggested_actions}

    @app.post("/approvals/propose")
    def approvals_propose(request: ProposalRequest, authorization: str | None = Header(default=None)) -> dict:
        return _rest_call(lambda: _approvals_propose_impl(request, authorization))

    def _approvals_propose_impl(request: ProposalRequest, authorization: str | None) -> dict:
        wiki = _resolve_wiki_by_id(request.wiki_id)
        actor = _resolve_actor(authorization)
        result = ApprovalService(registry_path=state["registry_path"]).propose(
            wiki=wiki,
            actor=actor,
            data=ProposalInput(
                proposal_id=request.proposal_id,
                doc_id=request.doc_id,
                page_type=request.page_type,
                topic=request.topic,
                problem_cluster=request.problem_cluster,
                content=request.content,
                source_refs=request.source_refs,
            ),
        )
        return {"status": result.status, "proposal_id": result.proposal_id}

    @app.post("/approvals/approve")
    def approvals_approve(request: ApproveRequest, authorization: str | None = Header(default=None)) -> dict:
        return _rest_call(lambda: _approvals_approve_impl(request, authorization))

    def _approvals_approve_impl(request: ApproveRequest, authorization: str | None) -> dict:
        wiki = _resolve_wiki_by_id(request.wiki_id)
        actor = _resolve_actor(authorization)
        result = ApprovalService(registry_path=state["registry_path"]).approve(
            wiki=wiki,
            actor=actor,
            proposal_id=request.proposal_id,
        )
        return {"status": result.status, "doc_id": result.doc_id}

    return app
