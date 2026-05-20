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

        missing_sections = self._missing_required_sections(content)
        if missing_sections:
            raise ValueError(f"quality gate failed: 5-section schema required; missing {', '.join(missing_sections)}")

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

    def _missing_required_sections(self, content: str) -> list[str]:
        required = ["Claims", "Applicability", "Evidence", "Relationship Hints", "Open Questions"]
        missing = []
        for section in required:
            section_pattern = r"\s+".join(re.escape(part) for part in section.split())
            pattern = rf"(?im)^##\s+{section_pattern}\s*$"
            if re.search(pattern, content) is None:
                missing.append(section)
        return missing

    def _critical_fact_coverage(self, content: str, source_refs: list[str]) -> float:
        content_tokens = set(re.findall(r"[a-z0-9_-]+", content.lower()))
        if not source_refs:
            return 0.0
        covered = 0
        for source_ref in source_refs:
            _, _, doc_id = source_ref.partition(":")
            tokens = set(re.findall(r"[a-z0-9_-]+", doc_id.lower()))
            if self._doc_id_covered(doc_id, content, content_tokens, tokens):
                covered += 1
        return covered / len(source_refs)

    def _doc_id_covered(self, doc_id: str, content: str, content_tokens: set[str], doc_id_tokens: set[str]) -> bool:
        lowered_content = content.lower()
        lowered_doc_id = doc_id.lower()

        if lowered_doc_id and lowered_doc_id in lowered_content:
            return True

        if doc_id_tokens and doc_id_tokens.issubset(content_tokens):
            return True

        content_bigrams = self._cjk_bigrams(content)
        doc_id_bigrams = self._cjk_bigrams(doc_id)
        if doc_id_bigrams:
            overlap = len(content_bigrams & doc_id_bigrams) / len(doc_id_bigrams)
            if overlap >= 0.5:
                return True
        return False

    def _cjk_bigrams(self, value: str) -> set[str]:
        chars = re.findall(r"[\u4e00-\u9fff]", value)
        if len(chars) < 2:
            return set()
        return {"".join(chars[index:index + 2]) for index in range(len(chars) - 1)}

    def _increment_warning(self, content: str, source_refs: list[str]) -> bool:
        words = re.findall(r"[a-z0-9_-]+", content.lower())
        if not words:
            return False
        unique_ratio = len(set(words)) / len(words)
        source_doc_ids = [source_ref.partition(":")[2].lower() for source_ref in source_refs]
        repeated_refs = sum(1 for doc_id in source_doc_ids if doc_id and doc_id in content.lower())
        overlap_heavy = len(source_doc_ids) >= 3 and repeated_refs >= len(source_doc_ids) - 1
        return unique_ratio < 0.45 or overlap_heavy
