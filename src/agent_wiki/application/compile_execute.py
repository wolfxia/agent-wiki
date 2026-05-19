from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from pydantic import BaseModel

from agent_wiki.application.compile_prepare import CompilePrepareInput, CompilePrepareResult, CompilePrepareService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.compile_apply import CompileApplyService, CompileStructuredOutput
from agent_wiki.application.compile_quality_gate import CompileQualityGate
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
        self._quality_gate_service = CompileQualityGate()
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
                result = self._run_packet_with_repairs(
                    wiki=wiki,
                    actor=actor,
                    packet=packet,
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
                error_type = self._classify_error(exc)
                queue.mark_failed(
                    packet.item_id,
                    str(exc),
                    content_state={
                        **self._attempt_telemetry(start_time, error_type=error_type),
                        **self._failure_stage(error_type),
                    },
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

    def _run_packet_with_repairs(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        packet: CompileExecutePacket,
        start_time: float,
    ) -> CompileResult:
        repair_strategy: str | None = None
        while True:
            try:
                content = self._apply_service.generate(wiki, packet.prepare)
                telemetry = self._attempt_telemetry(start_time, error_type=None)
                if repair_strategy:
                    telemetry["repair_strategy"] = repair_strategy
                return self.apply_generated(
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
            except Exception as exc:
                error_type = self._classify_error(exc)
                if error_type == "invalid_output" and repair_strategy is None:
                    repair_strategy = "output_repair_retry"
                    continue
                if error_type == "quality_rejected" and repair_strategy is None:
                    repair_strategy = "quality_rewrite_retry"
                    continue
                raise

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
                    telemetry = {**telemetry, **self._failure_stage(str(telemetry.get("error_type") or "unknown"))}
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
            quality = self._quality_gate_service.evaluate(data)
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
                        evidence_note=quality.get("evidence_note"),
                    ),
                )
                self._append_manifest_quality(
                    wiki_root=Path(wiki.workspace_path),
                    doc_id=data.doc_id,
                    quality=quality,
                )
        except Exception as exc:
            failure_telemetry = self._attempt_telemetry(
                started_at,
                error_type=self._classify_error(exc),
                base=telemetry,
            )
            error_type = str(failure_telemetry.get("error_type") or "unknown")
            queue.mark_failed(
                data.item_id,
                str(exc),
                content_state=self._persistable_telemetry({
                    **failure_telemetry,
                    **self._failure_stage(error_type),
                    "quality_gate": self._extract_quality_gate(exc),
                }),
            )
            raise

        resolved_telemetry = self._attempt_telemetry(started_at, error_type=None, base=telemetry)
        quality_status = quality.get("quality_status", "pass")
        with self._write_lock:
            queue.mark_resolved(
                data.item_id,
                {
                    "compiled_doc_id": result.doc_id,
                    "compile_result_status": result.status,
                    **self._persistable_telemetry(resolved_telemetry),
                    "quality_status": quality_status,
                    "quality_gate": quality,
                    "error_type": "quality_warning_committed" if quality_status == "warning" else None,
                    "retry_stage": "human_review" if quality_status == "warning" else None,
                    "repair_strategy": telemetry.get("repair_strategy") if telemetry else None,
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
            message = str(exc).lower()
            if "quality gate" in message or "critical_fact_coverage" in message:
                return "quality_rejected"
            return "invalid_output"
        return "write_error"

    def _append_manifest_quality(self, wiki_root: Path, doc_id: str, quality: dict) -> None:
        from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository

        ManifestRepository(wiki_root).upsert(
            {
                "doc_id": doc_id,
                "quality_status": quality.get("quality_status", "pass"),
                "quality_score_summary": {
                    "critical_fact_coverage": quality.get("critical_fact_coverage", 0.0),
                    "source_ref_coverage": quality.get("source_ref_coverage", 0.0),
                    "increment_warning": quality.get("increment_warning", False),
                },
                "quality_checked_at": quality.get("quality_checked_at"),
            }
        )

    def _failure_stage(self, error_type: str) -> dict:
        normalized = (error_type or "unknown").lower()
        if normalized in {"timeout", "5xx", "4xx_auth"}:
            return {"failure_stage": "generation", "retry_stage": "transport_retry"}
        if normalized == "invalid_output":
            return {"failure_stage": "generation", "retry_stage": "output_repair_retry"}
        if normalized == "quality_rejected":
            return {"failure_stage": "quality_gate", "retry_stage": "quality_rewrite_retry"}
        return {"failure_stage": "apply", "retry_stage": "human_review"}

    def _extract_quality_gate(self, exc: Exception) -> dict | None:
        message = str(exc)
        if "critical_fact_coverage=" not in message:
            return None
        try:
            parts = message.split("critical_fact_coverage=", maxsplit=1)[1]
            coverage_text = parts.split(",", maxsplit=1)[0]
            return {"critical_fact_coverage": float(coverage_text)}
        except Exception:
            return None

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
