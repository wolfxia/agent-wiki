import json
from agent_wiki._compat import UTC
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from agent_wiki.bootstrap.registry_loader import RuntimeTuningConfig, WikiConfig


_LOW_RISK_PARAMETERS = {
    "query_ranking.atom_page_type_boost",
    "query_ranking.synthesis_page_type_boost",
    "query_ranking.principle_page_type_boost",
    "query_ranking.purpose_boost",
    "query_ranking.topic_alignment_boost",
    "query_ranking.topic_seed_score",
    "query_ranking.rerank_candidate_multiplier",
    "query_ranking.freshness_penalty.penalty_weight",
    "query_ranking.confidence_penalty.ambiguous_penalty_weight",
}
_MAX_AUTO_TUNE_STEP = 1.0
_AUTO_TUNE_ROLLBACK_DROP_THRESHOLD = 0.02
_PENALTY_ROLLBACK_DROP_THRESHOLD = 0.05


class RuntimeTuningService:
    def load(self, wiki: WikiConfig) -> RuntimeTuningConfig:
        defaults = self._defaults(wiki)
        runtime_path = self._runtime_path(wiki)
        if not runtime_path.exists():
            return defaults
        runtime_data = self._read_json(runtime_path)
        if not isinstance(runtime_data, dict):
            return defaults
        return self._merge(defaults, runtime_data)

    def update_parameter(
        self,
        wiki: WikiConfig,
        parameter_name: str,
        new_value: Any,
        *,
        trigger: str,
        expected_effect: str,
        eval_before: dict,
    ) -> RuntimeTuningConfig:
        runtime_root = self._runtime_root(wiki)
        runtime_root.mkdir(parents=True, exist_ok=True)

        current = self.load(wiki)
        current_payload = current.model_dump(mode="json")
        old_value = self._nested_get(current_payload, parameter_name)
        updated_payload = self._nested_set(current_payload, parameter_name, new_value)
        updated = RuntimeTuningConfig.model_validate(updated_payload)

        self._runtime_path(wiki).write_text(
            json.dumps(updated.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._append_history(
            wiki,
            {
                "timestamp": self._timestamp(),
                "parameter_name": parameter_name,
                "old_value": old_value,
                "new_value": new_value,
                "trigger": trigger,
                "expected_effect": expected_effect,
                "eval_before": eval_before,
            },
        )
        return updated

    def freeze_baseline(self, wiki: WikiConfig) -> RuntimeTuningConfig:
        baseline = self.load(wiki)
        path = self._runtime_root(wiki) / "frozen_baseline.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(baseline.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return baseline

    def load_frozen_baseline(self, wiki: WikiConfig) -> RuntimeTuningConfig | None:
        path = self._runtime_root(wiki) / "frozen_baseline.json"
        if not path.exists():
            return None
        data = self._read_json(path)
        if not isinstance(data, dict):
            return None
        try:
            return RuntimeTuningConfig.model_validate(data)
        except ValidationError:
            return None

    def auto_tune(
        self,
        wiki: WikiConfig,
        diagnosis_report: dict[str, Any],
        *,
        eval_after: dict[str, Any] | None = None,
        evaluate_after: Callable[[], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        latest_eval = diagnosis_report.get("latest_eval") or {}
        eval_before = latest_eval.get("metrics") or {}
        if not eval_before:
            return {"status": "skipped", "reason": "missing_eval_baseline"}

        recommendation = self._select_auto_tune_recommendation(diagnosis_report.get("diagnoses") or [])
        if recommendation is None:
            return {"status": "skipped", "reason": "no_low_risk_recommendation"}

        parameter_name = str(recommendation["parameter_name"])
        current_payload = self.load(wiki).model_dump(mode="json")
        old_value = self._nested_get(current_payload, parameter_name)
        new_value = self._recommended_value(old_value, recommendation)
        if new_value is None or new_value == old_value:
            return {"status": "skipped", "reason": "no_effective_change", "parameter_name": parameter_name}

        self.update_parameter(
            wiki=wiki,
            parameter_name=parameter_name,
            new_value=new_value,
            trigger=f"auto_tune:{recommendation['diagnosis_type']}",
            expected_effect=str(recommendation.get("expected_effect") or "improve retrieval quality"),
            eval_before=eval_before,
        )

        after_report = eval_after
        if after_report is None and evaluate_after is not None:
            after_report = evaluate_after()

        if self._strict_recall_regressed(eval_before, after_report, parameter_name=parameter_name):
            self.update_parameter(
                wiki=wiki,
                parameter_name=parameter_name,
                new_value=old_value,
                trigger="auto_tune_rollback",
                expected_effect="restore previous value after strict recall regression",
                eval_before=(after_report or {}).get("metrics") or {},
            )
            return {
                "status": "rolled_back",
                "parameter_name": parameter_name,
                "old_value": old_value,
                "new_value": new_value,
                "eval_after": after_report,
            }

        return {
            "status": "changed",
            "parameter_name": parameter_name,
            "old_value": old_value,
            "new_value": new_value,
            "eval_after": after_report,
        }


    def enable_ranking_penalties(
        self,
        wiki: WikiConfig,
        *,
        eval_before: dict[str, Any],
        eval_after: dict[str, Any] | None,
    ) -> dict[str, Any]:
        before = self.load(wiki)
        before_payload = before.model_dump(mode="json")
        updated_payload = json.loads(json.dumps(before_payload))
        updated_payload["query_ranking"]["freshness_penalty"]["enabled"] = True
        updated_payload["query_ranking"]["confidence_penalty"]["enabled"] = True
        updated = RuntimeTuningConfig.model_validate(updated_payload)

        runtime_root = self._runtime_root(wiki)
        runtime_root.mkdir(parents=True, exist_ok=True)
        self._runtime_path(wiki).write_text(
            json.dumps(updated.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._append_history(
            wiki,
            {
                "timestamp": self._timestamp(),
                "parameter_name": "query_ranking.penalties.enabled",
                "old_value": {
                    "freshness_penalty": before.query_ranking.freshness_penalty.enabled,
                    "confidence_penalty": before.query_ranking.confidence_penalty.enabled,
                },
                "new_value": {"freshness_penalty": True, "confidence_penalty": True},
                "trigger": "ranking_penalty_enable",
                "expected_effect": "deprioritize stale and ambiguous atoms",
                "eval_before": eval_before,
            },
        )

        if self._strict_recall_regressed(
            eval_before,
            eval_after,
            parameter_name="query_ranking.freshness_penalty.enabled",
        ):
            self._runtime_path(wiki).write_text(
                json.dumps(before_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self._append_history(
                wiki,
                {
                    "timestamp": self._timestamp(),
                    "parameter_name": "query_ranking.penalties.enabled",
                    "old_value": {"freshness_penalty": True, "confidence_penalty": True},
                    "new_value": {
                        "freshness_penalty": before.query_ranking.freshness_penalty.enabled,
                        "confidence_penalty": before.query_ranking.confidence_penalty.enabled,
                    },
                    "trigger": "ranking_penalty_rollback",
                    "expected_effect": "restore previous penalty enablement after strict recall regression",
                    "eval_before": (eval_after or {}).get("metrics") or {},
                },
            )
            return {"status": "rolled_back", "eval_after": eval_after}

        return {"status": "changed", "eval_after": eval_after}

    def _defaults(self, wiki: WikiConfig) -> RuntimeTuningConfig:
        return RuntimeTuningConfig.model_validate(self._as_payload(getattr(wiki, "tuning_defaults", {})))

    def _select_auto_tune_recommendation(self, diagnoses: list[dict[str, Any]]) -> dict[str, Any] | None:
        for diagnosis in diagnoses:
            recommendation = diagnosis.get("recommendation") or {}
            if recommendation.get("action") != "adjust_parameter":
                continue
            parameter_name = str(recommendation.get("parameter_name") or "")
            if parameter_name not in _LOW_RISK_PARAMETERS:
                continue
            step = recommendation.get("step")
            if not isinstance(step, (int, float)) or step <= 0 or step > _MAX_AUTO_TUNE_STEP:
                continue
            return {
                **recommendation,
                "diagnosis_type": diagnosis.get("diagnosis_type") or "unknown",
            }
        return None

    def _recommended_value(self, old_value: Any, recommendation: dict[str, Any]) -> Any:
        if not isinstance(old_value, (int, float)):
            return None
        direction = str(recommendation.get("direction") or "increase").lower()
        step = float(recommendation.get("step") or 0)
        if direction == "decrease":
            candidate = float(old_value) - step
        else:
            candidate = float(old_value) + step
        if isinstance(old_value, int) and not isinstance(old_value, bool):
            return int(round(candidate))
        return round(candidate, 3)

    def _strict_recall_regressed(
        self,
        eval_before: dict[str, Any],
        eval_after: dict[str, Any] | None,
        *,
        parameter_name: str = "",
    ) -> bool:
        if not eval_after:
            return False
        after_metrics = eval_after.get("metrics") or {}
        before_strict = float(eval_before.get("strict_recall_at_k", 0.0) or 0.0)
        after_strict = float(after_metrics.get("strict_recall_at_k", 0.0) or 0.0)
        threshold = (
            _PENALTY_ROLLBACK_DROP_THRESHOLD
            if parameter_name.startswith("query_ranking.freshness_penalty")
            or parameter_name.startswith("query_ranking.confidence_penalty")
            else _AUTO_TUNE_ROLLBACK_DROP_THRESHOLD
        )
        return (before_strict - after_strict) > threshold

    def _merge(self, defaults: RuntimeTuningConfig, override: dict) -> RuntimeTuningConfig:
        merged = defaults.model_dump(mode="json")
        self._deep_merge(merged, override)
        return RuntimeTuningConfig.model_validate(merged)

    def _deep_merge(self, target: dict[str, Any], override: dict[str, Any]) -> None:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_merge(target[key], value)
                continue
            if isinstance(target.get(key), dict) and not isinstance(value, dict):
                continue
            target[key] = value

    def _nested_get(self, payload: dict[str, Any], parameter_name: str) -> Any:
        current: Any = payload
        for part in parameter_name.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _nested_set(self, payload: dict[str, Any], parameter_name: str, new_value: Any) -> dict[str, Any]:
        updated = json.loads(json.dumps(payload))
        current: dict[str, Any] = updated
        parts = parameter_name.split(".")
        for part in parts[:-1]:
            next_value = current.get(part)
            if not isinstance(next_value, dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = new_value
        return updated

    def _append_history(self, wiki: WikiConfig, entry: dict[str, Any]) -> None:
        path = self._runtime_root(wiki) / "param_history.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _runtime_root(self, wiki: WikiConfig) -> Path:
        return Path(wiki.workspace_path) / ".agent-wiki"

    def _runtime_path(self, wiki: WikiConfig) -> Path:
        return self._runtime_root(wiki) / "runtime_tuning.json"

    def _read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def _as_payload(self, value: Any) -> dict[str, Any]:
        if isinstance(value, RuntimeTuningConfig):
            return value.model_dump(mode="json")
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return value
        return {}

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
