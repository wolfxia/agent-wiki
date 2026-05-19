from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any


class CompileQualityGate:
    def evaluate(self, payload: dict[str, Any] | Any) -> dict:
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        summary = str(payload.get("summary") or "")
        confidence = str(payload.get("confidence") or "")
        content = str(payload.get("content") or "")
        source_refs = list(payload.get("source_refs") or [])

        if not (summary.strip() and confidence.strip() and content.strip()):
            raise ValueError("quality gate failed: summary/confidence/content required")

        lowered = content.lower()
        if "claims" not in lowered or "evidence" not in lowered:
            raise ValueError("quality gate failed: Claims + Evidence sections required")

        source_ref_coverage = 1.0 if source_refs else 0.0
        critical_fact_coverage = self._critical_fact_coverage(content, source_refs)
        if source_ref_coverage < 1.0 or critical_fact_coverage < 0.6:
            raise ValueError(
                f"quality gate failed: critical_fact_coverage={critical_fact_coverage:.3f}, source_ref_coverage={source_ref_coverage:.3f}"
            )

        increment_warning = self._increment_warning(content, source_refs)
        return {
            "quality_status": "warning" if increment_warning else "pass",
            "critical_fact_coverage": round(critical_fact_coverage, 3),
            "source_ref_coverage": round(source_ref_coverage, 3),
            "increment_warning": increment_warning,
            "structure_ok": True,
            "fields_ok": True,
            "quality_checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "evidence_note": "increment_warning" if increment_warning else None,
        }

    def _critical_fact_coverage(self, content: str, source_refs: list[str]) -> float:
        content_tokens = set(re.findall(r"[a-z0-9_-]+", content.lower()))
        if not source_refs:
            return 0.0
        covered = 0
        for source_ref in source_refs:
            _, _, doc_id = source_ref.partition(":")
            tokens = set(re.findall(r"[a-z0-9_-]+", doc_id.lower()))
            if tokens and tokens.issubset(content_tokens):
                covered += 1
        return covered / len(source_refs)

    def _increment_warning(self, content: str, source_refs: list[str]) -> bool:
        words = re.findall(r"[a-z0-9_-]+", content.lower())
        if not words:
            return False
        unique_ratio = len(set(words)) / len(words)
        source_doc_ids = [source_ref.partition(":")[2].lower() for source_ref in source_refs]
        repeated_refs = sum(1 for doc_id in source_doc_ids if doc_id and doc_id in content.lower())
        overlap_heavy = len(source_doc_ids) >= 3 and repeated_refs >= len(source_doc_ids) - 1
        return unique_ratio < 0.45 or overlap_heavy
