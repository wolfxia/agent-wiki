from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import re
import time
from pydantic import BaseModel

from agent_wiki.application.compile_prepare import CompilePrepareInput, CompilePrepareResult, CompilePrepareService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.compile_apply import CompileApplyService, CompileStructuredOutput, CompileClaim, CompileRelationshipHint
from agent_wiki.application.compile_quality_gate import CompileQualityGate
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CompileResult, CompileUpdateInput
from agent_wiki.infrastructure.runtime.claim_annotations import ClaimAnnotationRepository
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
    claims: list[CompileClaim] = []
    relationship_hints: list[CompileRelationshipHint] = []
    open_questions: list[str] = []
    evidence_coverage: str | None = None
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
        aliases = self._normalized_aliases(structured)
        return CompileGeneratedInput(
            item_id=packet.item_id,
            doc_id=packet.prepare.proposed_doc_id,
            page_type=packet.prepare.proposed_page_type,
            topic=packet.prepare.topic,
            problem_cluster=packet.prepare.problem_cluster,
            content=generated.content if generated else "",
            source_refs=packet.prepare.source_refs,
            summary=structured.summary if structured else None,
            aliases=aliases,
            confidence=structured.confidence if structured else None,
            wikilinks=structured.wikilinks if structured else [],
            claims=structured.claims if structured else [],
            relationship_hints=structured.relationship_hints if structured else [],
            open_questions=structured.open_questions if structured else [],
            evidence_coverage=structured.evidence_coverage if structured else None,
        )

    def _normalized_aliases(self, structured: CompileStructuredOutput | None) -> list[str]:
        if structured is None:
            return []
        aliases: list[str] = []
        seen: set[str] = set()

        def add(value: str) -> None:
            normalized = str(value).strip()
            if normalized.startswith("[[") and normalized.endswith("]]"):
                normalized = normalized[2:-2].strip()
            if not normalized:
                return
            key = normalized.lower()
            if key in seen:
                return
            seen.add(key)
            aliases.append(normalized)

        for alias in structured.aliases:
            add(alias)
        if aliases:
            return aliases
        for link in structured.wikilinks:
            add(link)
        for hint in structured.relationship_hints:
            add(hint.target_concept)
        if aliases:
            return aliases
        for alias in self._aliases_from_summary(structured.summary):
            add(alias)
        return aliases

    def _aliases_from_summary(self, summary: str | None) -> list[str]:
        if not summary:
            return []

        aliases: list[str] = []
        seen: set[str] = set()

        def capture(value: str) -> None:
            normalized = value.strip(" ,.;:()[]{}")
            if len(normalized) < 3:
                return
            key = normalized.lower()
            if key in seen:
                return
            seen.add(key)
            aliases.append(normalized)
            if "-" in normalized:
                head, tail = normalized.split("-", 1)
                if (
                    len(head) >= 3
                    and tail.islower()
                    and re.fullmatch(r"(?:[A-Z]{2,}\d*|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*)", head)
                ):
                    head_key = head.lower()
                    if head_key not in seen:
                        seen.add(head_key)
                        aliases.append(head)

        phrase_pattern = re.compile(
            r"\b(?:[A-Z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*|[A-Z]{2,}\d*(?:[-/][A-Za-z0-9]+)*)"
            r"(?:\s+(?:[A-Z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*|[A-Z]{2,}\d*(?:[-/][A-Za-z0-9]+)*)){1,2}\b"
        )
        token_pattern = re.compile(
            r"\b(?:[A-Z]{2,}\d*(?:[-/][A-Za-z0-9]+)*|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*"
            r"(?:[-/][A-Za-z0-9]+)*)\b"
        )

        for match in phrase_pattern.finditer(summary):
            capture(match.group(0))
        for match in token_pattern.finditer(summary):
            capture(match.group(0))
        return aliases[:6]

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
            normalized_data = self._with_required_sections(data)
            quality = self._quality_gate_service.evaluate(normalized_data)
            with self._write_lock:
                result = CompileUpdateService().apply(
                    wiki=wiki,
                    actor=actor,
                    data=CompileUpdateInput(
                        doc_id=normalized_data.doc_id,
                        page_type=normalized_data.page_type,
                        topic=normalized_data.topic,
                        problem_cluster=normalized_data.problem_cluster,
                        summary=normalized_data.summary,
                        aliases=normalized_data.aliases,
                        confidence=normalized_data.confidence,
                        contested=normalized_data.contested,
                        wikilinks=normalized_data.wikilinks,
                        sensitivity=normalized_data.sensitivity,
                        review_status="pending_review",
                        content=normalized_data.content,
                        source_refs=normalized_data.source_refs,
                        evidence_note=quality.get("evidence_note"),
                    ),
                )
                wiki_root = Path(wiki.workspace_path)
                self._append_manifest_quality(
                    wiki_root=wiki_root,
                    doc_id=data.doc_id,
                    quality=quality,
                )
                self._write_claim_annotations(wiki_root, normalized_data)
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

    def _with_required_sections(self, data: CompileGeneratedInput) -> CompileGeneratedInput:
        content = data.content.strip()
        additions: list[str] = []
        if not self._has_section(content, "Claims"):
            additions.append(self._section("Claims", self._claim_lines(data)))
        if not self._has_section(content, "Applicability"):
            additions.append(self._section("Applicability", ["None identified from source evidence."]))
        if not self._has_section(content, "Evidence"):
            additions.append(self._section("Evidence", data.source_refs or ["None identified from source evidence."]))
        if not self._has_section(content, "Relationship Hints"):
            additions.append(self._section("Relationship Hints", self._relationship_hint_lines(data)))
        if not self._has_section(content, "Open Questions"):
            additions.append(self._section("Open Questions", data.open_questions or ["None identified from source evidence."]))
        if additions:
            content = content + "\n\n" + "\n\n".join(additions)
        return data.model_copy(update={"content": content})

    def _has_section(self, content: str, section: str) -> bool:
        section_pattern = r"\s+".join(re.escape(part) for part in section.split())
        pattern = rf"(?im)^##\s+{section_pattern}\s*$"
        return re.search(pattern, content) is not None

    def _section(self, heading: str, lines: list[str]) -> str:
        body = [str(line).strip() for line in lines if str(line).strip()] or ["None identified from source evidence."]
        return "## " + heading + "\n" + "\n".join(line if line.startswith("-") else f"- {line}" for line in body)

    def _claim_lines(self, data: CompileGeneratedInput) -> list[str]:
        if data.claims:
            return [claim.text for claim in data.claims]
        return ["None identified from source evidence."]

    def _relationship_hint_lines(self, data: CompileGeneratedInput) -> list[str]:
        if not data.relationship_hints:
            return ["None identified from source evidence."]
        lines = []
        for hint in data.relationship_hints:
            source = f"{hint.source_doc} -> " if hint.source_doc else ""
            lines.append(f"{source}{hint.target_concept} ({hint.hint_type})")
        return lines

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


    def _write_claim_annotations(self, wiki_root: Path, data: CompileGeneratedInput) -> None:
        if data.page_type != "atom" or not data.claims:
            return
        ClaimAnnotationRepository(wiki_root).upsert(
            {
                "doc_id": data.doc_id,
                "claims": [
                    {
                        "text": claim.text,
                        "confidence_label": claim.confidence_label,
                        "evidence_refs": claim.evidence_refs,
                        "rationale": "compile structured output",
                    }
                    for claim in data.claims
                ],
                "annotation_method": "compile",
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
