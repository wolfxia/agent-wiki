from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from agent_wiki.application.capture_raw import CaptureRawService
from agent_wiki.application.query import QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CaptureRawInput, QueryInput


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


def create_app(wiki_workspace: str | None = None) -> FastAPI:
    app = FastAPI(title="agent-wiki")
    state: dict[str, Any] = {"wiki_workspace": wiki_workspace}

    def _resolve_wiki():
        registry = RegistryLoader().load(Path("tests/fixtures/registry.yaml"))
        wiki = registry.wikis[0]
        if state["wiki_workspace"]:
            wiki = wiki.model_copy(update={"workspace_path": state["wiki_workspace"]})
        return wiki

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "agent-wiki"}

    @app.post("/query")
    def query(request: QueryRequest) -> dict:
        wiki = _resolve_wiki()
        actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="rest")
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
    def capture_raw(request: CaptureRequest) -> dict:
        wiki = _resolve_wiki()
        actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="rest")
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
