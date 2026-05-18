from pathlib import Path
from pydantic import BaseModel

from agent_wiki.application.compile_prepare import CompilePrepareInput, CompilePrepareResult, CompilePrepareService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CompileResult, CompileUpdateInput
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository


class CompileExecuteInput(BaseModel):
    limit: int = 1
    priority_filter: str | None = None


class CompileExecutePacket(BaseModel):
    item_id: str
    item_type: str
    priority_label: str | None = None
    prepare: CompilePrepareResult


class CompileGeneratedInput(BaseModel):
    item_id: str
    doc_id: str
    page_type: str
    topic: str
    problem_cluster: str
    content: str
    source_refs: list[str]
    summary: str | None = None
    aliases: list[str] = []
    confidence: str | None = None
    contested: bool = False
    wikilinks: list[str] = []
    sensitivity: str | None = None


class CompileExecuteService:
    def prepare_next(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        data: CompileExecuteInput,
    ) -> list[CompileExecutePacket]:
        queue = ReviewQueueRepository(Path(wiki.workspace_path))
        packets: list[CompileExecutePacket] = []
        for _ in range(max(data.limit, 0)):
            item = queue.consume(
                "compile_suggestion",
                actor_id=actor.actor_id,
                priority_filter=data.priority_filter,
            )
            if item is None:
                break
            prepare_params = item.get("prepare_params") or {}
            prepare = CompilePrepareService().prepare(
                wiki=wiki,
                actor=actor,
                data=CompilePrepareInput(
                    topic=prepare_params.get("topic") or item.get("topic") or "",
                    problem_cluster=prepare_params.get("problem_cluster") or item.get("problem_cluster") or "",
                    doc_ids=prepare_params.get("doc_ids") or item.get("raw_doc_ids") or None,
                    max_items=prepare_params.get("max_items", 8),
                    sub_cluster_index=prepare_params.get("sub_cluster_index") or item.get("sub_cluster_index") or 1,
                ),
            )
            packets.append(
                CompileExecutePacket(
                    item_id=str(item.get("item_id")),
                    item_type=str(item.get("item_type")),
                    priority_label=item.get("priority_label"),
                    prepare=prepare,
                )
            )
        return packets

    def apply_generated(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        data: CompileGeneratedInput,
    ) -> CompileResult:
        queue = ReviewQueueRepository(Path(wiki.workspace_path))
        try:
            result = CompileUpdateService().apply(
                wiki=wiki,
                actor=actor,
                data=CompileUpdateInput(
                    doc_id=data.doc_id,
                    page_type=data.page_type,
                    topic=data.topic,
                    problem_cluster=data.problem_cluster,
                    summary=data.summary,
                    aliases=data.aliases,
                    confidence=data.confidence,
                    contested=data.contested,
                    wikilinks=data.wikilinks,
                    sensitivity=data.sensitivity,
                    review_status="pending_review",
                    content=data.content,
                    source_refs=data.source_refs,
                ),
            )
        except Exception as exc:
            queue.mark_failed(data.item_id, str(exc))
            raise

        queue.mark_resolved(
            data.item_id,
            {
                "compiled_doc_id": result.doc_id,
                "compile_result_status": result.status,
            },
        )
        return result
