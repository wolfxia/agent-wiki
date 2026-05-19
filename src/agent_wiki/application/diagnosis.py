import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent_wiki.application.quality_report import QualityReportService
from agent_wiki.application.runtime_tuning import RuntimeTuningService
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository

_EVAL_DROP_THRESHOLD = 0.05
_QUALITY_COMPLETENESS_THRESHOLD = 0.8
_ZERO_HIT_THRESHOLD = 3
_HOT_DOC_THRESHOLD = 3


class DiagnosisService:
    def __init__(self) -> None:
        self._runtime_tuning = RuntimeTuningService()
        self._quality_report = QualityReportService()

    def analyze(self, wiki: WikiConfig) -> dict[str, Any]:
        wiki_root = Path(wiki.workspace_path)
        quality_report = self._quality_report.generate(wiki)
        eval_history = self._read_jsonl(wiki_root / ".agent-wiki" / "eval_history.jsonl")
        diagnoses: list[dict[str, Any]] = []

        parameter_drift = self._parameter_drift_diagnosis(wiki)
        if parameter_drift is not None:
            diagnoses.append(parameter_drift)

        retrieval_shift = self._retrieval_shift_diagnosis(wiki, eval_history, quality_report)
        if retrieval_shift is not None:
            diagnoses.append(retrieval_shift)

        compile_degradation = self._compile_quality_diagnosis(quality_report)
        if compile_degradation is not None:
            diagnoses.append(compile_degradation)

        coverage_gap = self._coverage_gap_diagnosis(wiki_root, quality_report)
        if coverage_gap is not None:
            diagnoses.append(coverage_gap)

        staleness = self._staleness_diagnosis(wiki, wiki_root)
        if staleness is not None:
            diagnoses.append(staleness)

        return {
            "diagnoses": diagnoses,
            "quality_report": quality_report,
            "latest_eval": eval_history[-1] if eval_history else None,
        }

    def _parameter_drift_diagnosis(self, wiki: WikiConfig) -> dict[str, Any] | None:
        frozen = self._runtime_tuning.load_frozen_baseline(wiki)
        if frozen is None:
            return None
        current = self._runtime_tuning.load(wiki)
        for parameter_name, current_value in self._flatten(current.model_dump(mode="json")).items():
            baseline_value = self._flatten(frozen.model_dump(mode="json")).get(parameter_name)
            if baseline_value == current_value:
                continue
            return {
                "diagnosis_type": "parameter_drift",
                "evidence": {
                    "parameter_name": parameter_name,
                    "current_value": current_value,
                    "baseline_value": baseline_value,
                },
                "recommendation": {
                    "action": "restore_frozen_baseline",
                    "parameter_name": parameter_name,
                    "target_value": baseline_value,
                },
            }
        return None

    def _retrieval_shift_diagnosis(self, wiki: WikiConfig, eval_history: list[dict], quality_report: dict[str, Any]) -> dict[str, Any] | None:
        if len(eval_history) < 2:
            return None
        previous = eval_history[-2].get("metrics") or {}
        latest = eval_history[-1].get("metrics") or {}
        strict_delta = float(latest.get("strict_recall_at_k", 0.0) or 0.0) - float(previous.get("strict_recall_at_k", 0.0) or 0.0)
        compiled_delta = float(latest.get("compiled_hit_ratio", 0.0) or 0.0) - float(previous.get("compiled_hit_ratio", 0.0) or 0.0)
        if strict_delta > -_EVAL_DROP_THRESHOLD:
            return None
        if (
            quality_report.get("compiled_count", 0) > 0
            and quality_report.get("atom_field_completeness", 1.0) < _QUALITY_COMPLETENESS_THRESHOLD
        ):
            return None
        return {
            "diagnosis_type": "retrieval_ranking_shift",
            "evidence": {
                "strict_recall_delta": strict_delta,
                "compiled_hit_ratio_delta": compiled_delta,
            },
            "recommendation": {
                "action": "adjust_parameter",
                "parameter_name": "query_ranking.topic_alignment_boost",
                "direction": "increase",
                "step": 0.5,
                "expected_effect": "recover strict recall for topic-aligned compiled pages",
                "current_value": self._runtime_tuning.load(wiki).query_ranking.topic_alignment_boost,
            },
        }

    def _compile_quality_diagnosis(self, quality_report: dict[str, Any]) -> dict[str, Any] | None:
        failure_breakdown = quality_report.get("compile_failure_breakdown") or {}
        if quality_report.get("compiled_count", 0) == 0 and not failure_breakdown:
            return None
        if (
            quality_report.get("atom_field_completeness", 1.0) >= _QUALITY_COMPLETENESS_THRESHOLD
            and quality_report.get("section_structure_compliance", 1.0) >= _QUALITY_COMPLETENESS_THRESHOLD
            and failure_breakdown.get("quality_rejected", 0) == 0
        ):
            return None
        return {
            "diagnosis_type": "compile_quality_degradation",
            "evidence": {
                "atom_field_completeness": quality_report.get("atom_field_completeness", 0.0),
                "section_structure_compliance": quality_report.get("section_structure_compliance", 0.0),
                "source_ref_coverage": quality_report.get("source_ref_coverage", 0.0),
                "compile_failure_breakdown": failure_breakdown,
            },
            "recommendation": {
                "action": "tighten_compile_prompt_or_repair",
                "expected_effect": "raise structure compliance and reduce quality_rejected failures",
            },
        }

    def _coverage_gap_diagnosis(self, wiki_root: Path, quality_report: dict[str, Any]) -> dict[str, Any] | None:
        zero_hit_queries = self._zero_hit_queries(wiki_root)
        if not zero_hit_queries:
            return None
        if max(zero_hit_queries.values()) < _ZERO_HIT_THRESHOLD and quality_report.get("cluster_coverage", 1.0) >= 0.5:
            return None
        return {
            "diagnosis_type": "coverage_gap",
            "evidence": {
                "cluster_coverage": quality_report.get("cluster_coverage", 0.0),
                "mature_cluster_coverage": quality_report.get("mature_cluster_coverage", 0.0),
                "zero_hit_queries": dict(zero_hit_queries),
            },
            "recommendation": {
                "action": "expand_compile_coverage",
                "expected_effect": "reduce recurring zero-hit queries by compiling missing clusters",
            },
        }

    def _staleness_diagnosis(self, wiki: WikiConfig, wiki_root: Path) -> dict[str, Any] | None:
        hot_doc_counts = self._accepted_doc_counts(wiki_root)
        if not hot_doc_counts:
            return None
        staleness_days = int(getattr(wiki.dream_cycle.quality, "staleness_days", 30))
        cutoff = datetime.now(UTC) - timedelta(days=staleness_days)
        stale_doc_ids: list[str] = []
        manifest = ManifestRepository(wiki_root)
        for doc_id, count in hot_doc_counts.items():
            if count < _HOT_DOC_THRESHOLD:
                continue
            entry = manifest.find(doc_id)
            if entry is None or not self._is_stale(entry.get("updated_at") or entry.get("updated"), cutoff):
                continue
            stale_doc_ids.append(doc_id)
        if not stale_doc_ids:
            return None
        stale_doc_ids.sort()
        return {
            "diagnosis_type": "staleness",
            "evidence": {
                "hot_doc_counts": {doc_id: hot_doc_counts[doc_id] for doc_id in stale_doc_ids},
                "staleness_days": staleness_days,
            },
            "recommendation": {
                "action": "refresh_hot_cluster",
                "doc_ids": stale_doc_ids,
                "expected_effect": "refresh high-traffic but stale compiled knowledge",
            },
        }

    def _read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _flatten(self, payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                flattened.update(self._flatten(value, path))
                continue
            flattened[path] = value
        return flattened

    def _zero_hit_queries(self, wiki_root: Path) -> Counter[str]:
        counts: Counter[str] = Counter()
        for entry in self._read_jsonl(wiki_root / "query_outcomes.jsonl"):
            if "query" not in entry or "hit_count" not in entry:
                continue
            if int(entry.get("hit_count", 0) or 0) == 0:
                counts[str(entry["query"])] += 1
        return counts

    def _accepted_doc_counts(self, wiki_root: Path) -> dict[str, int]:
        counts: defaultdict[str, int] = defaultdict(int)
        for entry in self._read_jsonl(wiki_root / "query_outcomes.jsonl"):
            for doc_id in entry.get("accepted_doc_ids") or []:
                counts[str(doc_id)] += 1
        return dict(counts)

    def _is_stale(self, updated_value: str | None, cutoff: datetime) -> bool:
        if not updated_value:
            return False
        try:
            parsed = datetime.fromisoformat(str(updated_value).replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC) < cutoff
