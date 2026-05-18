from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from pydantic import BaseModel

from agent_wiki.application.compile_prepare import CompilePrepareInput, CompilePrepareResult, CompilePrepareService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.compile_apply import CompileApplyService, CompileStructuredOutput
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CompileResult, CompileUpdateInput
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository


class CompileExecuteInput(BaseModel):
    limit: int = 1
    priority_filter: str | None = None
    concurrency: int = 1


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


class GeneratedCompilePacket(BaseModel):
    content: str
    structured_output: CompileStructuredOutput | None = None


class CompileExecuteService:
    def __init__(self, apply_service: CompileApplyService | None = None) -> None:
        self._apply_service = apply_service or CompileApplyService()
        self._write_lock = threading.Lock()

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
        if max(data.concurrency, 1) > 1:
            return self._apply_next_concurrent(wiki, actor, packets, max(data.concurrency, 1))
        results: list[CompileExecuteResult] = []
        for packet in packets:
            failed = False
            start_time = time.monotonic()
            try:
                content = self._apply_service.generate(wiki, packet.prepare)
                telemetry = self._attempt_telemetry(start_time, error_type=None)
                result = self.apply_generated(
                    wiki=wiki,
                    actor=actor,
                    data=self._generated_input_from_packet(
                        packet=packet,
                        generated=GeneratedCompilePacket(
                            content=content,
                            structured_output=getattr(self._apply_service, "last_structured_output", None),
                        ),
                    ),
                    telemetry=telemetry,
                    start_time=start_time,
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
                queue.mark_failed(
                    packet.item_id,
                    str(exc),
                    content_state=self._attempt_telemetry(start_time, error_type=self._classify_error(exc)),
                )
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

    def _apply_next_concurrent(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        packets: list[CompileExecutePacket],
        concurrency: int,
    ) -> list[CompileExecuteResult]:
        generated: list[tuple[CompileExecutePacket, GeneratedCompilePacket | None, dict, Exception | None]] = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(self._generate_packet, wiki, packet) for packet in packets]
            for packet, future in zip(packets, futures, strict=True):
                try:
                    generated_packet, telemetry = future.result()
                    generated.append((packet, generated_packet, telemetry, None))
                except Exception as exc:
                    telemetry = getattr(exc, "compile_telemetry", None)
                    if not isinstance(telemetry, dict):
                        telemetry = {"latency_seconds": 0.0, "attempts": 1, "error_type": self._classify_error(exc)}
                    generated.append((packet, None, telemetry, exc))

        results: list[CompileExecuteResult] = []
        for packet, generated_packet, telemetry, error in generated:
            if error is not None:
                queue = ReviewQueueRepository(Path(wiki.workspace_path))
                queue.mark_failed(packet.item_id, str(error), content_state=telemetry)
                queue.release_assignment(packet.item_id)
                results.append(
                    CompileExecuteResult(
                        item_id=packet.item_id,
                        status="failed",
                        queue_status="failed",
                        error=str(error),
                        fallback_priority=packet.fallback_priority,
                    )
                )
                continue
            try:
                result = self.apply_generated(
                    wiki=wiki,
                    actor=actor,
                    data=self._generated_input_from_packet(packet=packet, generated=generated_packet),
                    telemetry=telemetry,
                    start_time=telemetry.get("_start_time") if telemetry else None,
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
                ReviewQueueRepository(Path(wiki.workspace_path)).release_assignment(packet.item_id)
                results.append(
                    CompileExecuteResult(
                        item_id=packet.item_id,
                        status="failed",
                        queue_status="failed",
                        error=str(exc),
                        fallback_priority=packet.fallback_priority,
                    )
                )
        return results

    def _generate_packet(self, wiki: WikiConfig, packet: CompileExecutePacket) -> tuple[GeneratedCompilePacket, dict]:
        start_time = time.monotonic()
        apply_service = self._apply_service_for_generate()
        try:
            content = apply_service.generate(wiki, packet.prepare)
        except Exception as exc:
            exc.compile_telemetry = self._attempt_telemetry(
                start_time,
                error_type=self._classify_error(exc, apply_service=apply_service),
                apply_service=apply_service,
            )
            raise
        telemetry = self._attempt_telemetry(start_time, error_type=None, apply_service=apply_service)
        telemetry["_start_time"] = start_time
        return GeneratedCompilePacket(
            content=content,
            structured_output=getattr(apply_service, "last_structured_output", None),
        ), telemetry

    def _generated_input_from_packet(
        self,
        packet: CompileExecutePacket,
        generated: GeneratedCompilePacket | None,
    ) -> CompileGeneratedInput:
        structured = generated.structured_output if generated else None
        return CompileGeneratedInput(
            item_id=packet.item_id,
            doc_id=packet.prepare.proposed_doc_id,
            page_type=packet.prepare.proposed_page_type,
            topic=packet.prepare.topic,
            problem_cluster=packet.prepare.problem_cluster,
            content=generated.content if generated else "",
            source_refs=packet.prepare.source_refs,
            summary=structured.summary if structured else None,
            aliases=structured.aliases if structured else [],
            confidence=structured.confidence if structured else None,
            wikilinks=structured.wikilinks if structured else [],
        )

    def apply_generated(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        data: CompileGeneratedInput,
        telemetry: dict | None = None,
        start_time: float | None = None,
    ) -> CompileResult:
        queue = ReviewQueueRepository(Path(wiki.workspace_path))
        started_at = start_time or time.monotonic()
        try:
            with self._write_lock:
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
            failure_telemetry = self._attempt_telemetry(
                started_at,
                error_type=self._classify_error(exc),
                base=telemetry,
            )
            queue.mark_failed(data.item_id, str(exc), content_state=self._persistable_telemetry(failure_telemetry))
            raise

        resolved_telemetry = self._attempt_telemetry(started_at, error_type=None, base=telemetry)
        with self._write_lock:
            queue.mark_resolved(
                data.item_id,
                {
                    "compiled_doc_id": result.doc_id,
                    "compile_result_status": result.status,
                    **self._persistable_telemetry(resolved_telemetry),
                },
            )
        return result

    def _attempt_telemetry(
        self,
        start_time: float,
        error_type: str | None,
        apply_service: object | None = None,
        base: dict | None = None,
    ) -> dict:
        service = apply_service or self._apply_service
        telemetry = dict(base or {})
        telemetry.pop("_start_time", None)
        token_usage = getattr(service, "last_usage", None) or telemetry.get("token_usage")
        telemetry = {
            **telemetry,
            "latency_seconds": round(max(time.monotonic() - start_time, 0.0), 3),
            "attempts": int(getattr(service, "last_attempts", telemetry.get("attempts", 1)) or 1),
            "error_type": error_type,
        }
        if isinstance(token_usage, dict):
            telemetry["token_usage"] = token_usage
        return telemetry

    def _classify_error(self, exc: Exception, apply_service: object | None = None) -> str:
        service = apply_service or self._apply_service
        explicit = getattr(service, "last_error_type", None)
        if explicit:
            return str(explicit)
        message = str(exc).lower()
        if isinstance(exc, (TimeoutError,)) or "timeout" in message or "timed out" in message:
            return "timeout"
        if "invalid doc_id" in message:
            return "doc_id_error"
        if isinstance(exc, ValueError):
            return "invalid_output"
        return "write_error"

    def _apply_service_for_generate(self) -> object:
        if isinstance(self._apply_service, CompileApplyService):
            return CompileApplyService(
                http_post=self._apply_service._http_post,
                sleep=self._apply_service._sleep,
                max_retries=self._apply_service._max_retries_override,
                retry_delays=self._apply_service._retry_delays_override,
            )
        return self._apply_service

    def _persistable_telemetry(self, telemetry: dict) -> dict:
        return {key: value for key, value in telemetry.items() if not key.startswith("_")}
