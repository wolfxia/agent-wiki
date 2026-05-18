from pathlib import Path
from pydantic import BaseModel

from agent_wiki.application.compile_prepare import CompilePrepareInput, CompilePrepareResult, CompilePrepareService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.compile_apply import CompileApplyService
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


class CompileExecuteResult(BaseModel):
    item_id: str
    status: str
    queue_status: str
    doc_id: str | None = None
    error: str | None = None


class CompileExecuteService:
    def __init__(self, apply_service: CompileApplyService | None = None) -> None:
        self._apply_service = apply_service or CompileApplyService()

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


    def apply_next(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        data: CompileExecuteInput,
    ) -> list[CompileExecuteResult]:
        packets = self.prepare_next(wiki=wiki, actor=actor, data=data)
        results: list[CompileExecuteResult] = []
        for packet in packets:
            try:
                content = self._apply_service.generate(wiki, packet.prepare)
                result = self.apply_generated(
                    wiki=wiki,
                    actor=actor,
                    data=CompileGeneratedInput(
                        item_id=packet.item_id,
                        doc_id=packet.prepare.proposed_doc_id,
                        page_type=packet.prepare.proposed_page_type,
                        topic=packet.prepare.topic,
                        problem_cluster=packet.prepare.problem_cluster,
                        content=content,
                        source_refs=packet.prepare.source_refs,
                    ),
                )
                queue_status = ReviewQueueRepository(Path(wiki.workspace_path)).find(packet.item_id).get("status", "unknown")
                results.append(
                    CompileExecuteResult(
                        item_id=packet.item_id,
                        status=result.status,
                        queue_status=queue_status,
                        doc_id=result.doc_id,
                    )
                )
            except Exception as exc:
                queue = ReviewQueueRepository(Path(wiki.workspace_path))
                queue.mark_failed(packet.item_id, str(exc))
                results.append(
                    CompileExecuteResult(
                        item_id=packet.item_id,
                        status="failed",
                        queue_status="failed",
                        error=str(exc),
                    )
                )
        return results

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
