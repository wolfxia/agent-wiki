from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from agent_wiki.application.capture_raw import CaptureRawService
from agent_wiki.application.query import QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CaptureRawInput, IdentityContext, QueryInput
from agent_wiki.infrastructure.identity.resolver import IdentityResolver
from agent_wiki.settings import DEFAULT_REGISTRY_PATH


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


def create_app(
    wiki_workspace: str | None = None,
    registry_path: str | None = None,
    token_identities: dict[str, dict[str, str]] | None = None,
) -> FastAPI:
    app = FastAPI(title="agent-wiki")
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
            "hit_count": result.hit_count,
            "miss_signal": result.miss_signal,
            "hits": [{"doc_id": h.doc_id, "score": h.score} for h in result.hits],
        }

    @app.post("/capture-raw")
    def capture_raw(request: CaptureRequest, authorization: str | None = Header(default=None)) -> dict:
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

    return app
