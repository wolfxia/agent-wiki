import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_wiki.bootstrap.registry_loader import RuntimeTuningConfig, WikiConfig


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

    def _defaults(self, wiki: WikiConfig) -> RuntimeTuningConfig:
        return RuntimeTuningConfig.model_validate(self._as_payload(getattr(wiki, "tuning_defaults", {})))

    def _merge(self, defaults: RuntimeTuningConfig, override: dict) -> RuntimeTuningConfig:
        merged = defaults.model_dump(mode="json")
        self._deep_merge(merged, override)
        return RuntimeTuningConfig.model_validate(merged)

    def _deep_merge(self, target: dict[str, Any], override: dict[str, Any]) -> None:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_merge(target[key], value)
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
            current = current.setdefault(part, {})
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
