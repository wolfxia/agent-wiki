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
    fallback_priority: str | None = None
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
    fallback_priority: str | None = None


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
            item, fallback_priority = self._consume_compile_suggestion(queue, actor, data.priority_filter)
            if item is None:
                break
            prepare_params = self._prepare_params_from_item(item)
            prepare = CompilePrepareService().prepare(
                wiki=wiki,
                actor=actor,
                data=CompilePrepareInput(
                    topic=prepare_params["topic"],
                    problem_cluster=prepare_params["problem_cluster"],
                    doc_ids=prepare_params["doc_ids"],
                    max_items=prepare_params.get("max_items", 8),
                    sub_cluster_index=prepare_params["sub_cluster_index"],
                ),
            )
            packets.append(
                CompileExecutePacket(
                    item_id=str(item.get("item_id")),
                    item_type=str(item.get("item_type")),
                    priority_label=item.get("priority_label"),
                    fallback_priority=fallback_priority,
                    prepare=prepare,
                )
            )
        return packets

    def _prepare_params_from_item(self, item: dict) -> dict:
        prepare_params = dict(item.get("prepare_params") or {})
        topic, problem_cluster, sub_cluster_index = self._parse_compile_suggestion_item_id(
            str(item.get("item_id") or "")
        )
        return {
            "topic": prepare_params.get("topic") or item.get("topic") or topic,
            "problem_cluster": prepare_params.get("problem_cluster") or item.get("problem_cluster") or problem_cluster,
            "doc_ids": prepare_params.get("doc_ids") or item.get("raw_doc_ids") or None,
            "max_items": prepare_params.get("max_items", 8),
            "sub_cluster_index": (
                prepare_params.get("sub_cluster_index")
                or item.get("sub_cluster_index")
                or sub_cluster_index
            ),
        }

    def _parse_compile_suggestion_item_id(self, item_id: str) -> tuple[str, str, int]:
        parts = item_id.split(":")
        if len(parts) < 3 or parts[0] != "compile_suggestion":
            return "", "", 1

        index = 1
        cluster_parts = parts[2:]
        if len(parts) >= 4:
            try:
                index = int(parts[-1])
                cluster_parts = parts[2:-1]
            except ValueError:
                index = 1
        return parts[1], ":".join(cluster_parts), index

    def _consume_compile_suggestion(
        self,
        queue: ReviewQueueRepository,
        actor: ResolvedActor,
        priority_filter: str | None,
    ) -> tuple[dict | None, str | None]:
        item = queue.consume(
            "compile_suggestion",
            actor_id=actor.actor_id,
            priority_filter=priority_filter,
        )
        if item is not None:
            return item, None
        if priority_filter and priority_filter.upper() == "P0":
            fallback_priority = "P1"
            fallback_item = queue.consume(
                "compile_suggestion",
                actor_id=actor.actor_id,
                priority_filter=fallback_priority,
            )
            if fallback_item is not None:
                return fallback_item, fallback_priority
        return None, None


    def apply_next(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        data: CompileExecuteInput,
    ) -> list[CompileExecuteResult]:
        packets = self.prepare_next(wiki=wiki, actor=actor, data=data)
        results: list[CompileExecuteResult] = []
        for packet in packets:
            failed = False
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
                        fallback_priority=packet.fallback_priority,
                    )
                )
            except Exception as exc:
                queue = ReviewQueueRepository(Path(wiki.workspace_path))
                queue.mark_failed(packet.item_id, str(exc))
                failed = True
                results.append(
                    CompileExecuteResult(
                        item_id=packet.item_id,
                        status="failed",
                        queue_status="failed",
                        error=str(exc),
                        fallback_priority=packet.fallback_priority,
                    )
                )
            finally:
                if failed:
                    ReviewQueueRepository(Path(wiki.workspace_path)).release_assignment(packet.item_id)
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
