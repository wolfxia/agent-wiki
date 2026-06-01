from __future__ import annotations

import json
from datetime import UTC, datetime
import time
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

from agent_wiki.application.query import QueryService
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import QueryInput
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class RetrievalEvalQuery(BaseModel):
    query: str
    query_type: str
    expected_doc_ids: list[str] = Field(default_factory=list)
    acceptable_doc_ids: list[str] = Field(default_factory=list)
    must_not_doc_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class EvalRetrievalService:
    def run(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        eval_file: Path,
        k: int = 5,
        page_types: list[str] | None = None,
    ) -> dict[str, Any]:
        wiki_root = Path(wiki.workspace_path)
        queries = self._read_queries(eval_file)
        manifest = ManifestRepository(wiki_root)
        manifest_by_doc_id = {
            str(entry.get("doc_id")): entry
            for entry in manifest.read_all()
            if entry.get("doc_id")
        }
        rows: list[dict[str, Any]] = []
        latencies: list[float] = []
        strict_recall_values: list[float] = []
        loose_recall_values: list[float] = []
        must_not_violation_values: list[float] = []
        precision_values: list[float] = []
        reciprocal_ranks: list[float] = []
        compiled_hits = 0
        total_hits = 0

        for item in queries:
            start = time.monotonic()
            result = QueryService().execute(
                wiki=wiki,
                actor=actor,
                data=QueryInput(query=item.query, page_types=page_types),
                write_outcome=False,
                write_side_effects=False,
            )
            latency_ms = round(max(time.monotonic() - start, 0.0) * 1000, 3)
            latencies.append(latency_ms)
            hits = result.hits[:k]
            hit_doc_ids = [hit.doc_id for hit in hits]
            relevant = set(item.expected_doc_ids) | set(item.acceptable_doc_ids)
            expected = set(item.expected_doc_ids)
            relevant_hits = [doc_id for doc_id in hit_doc_ids if doc_id in relevant]
            expected_hits = [doc_id for doc_id in hit_doc_ids if doc_id in expected]
            must_not_hits = [doc_id for doc_id in hit_doc_ids if doc_id in set(item.must_not_doc_ids)]

            strict_recall_values.append(len(expected_hits) / len(expected) if expected else 0.0)
            loose_recall_values.append(1.0 if relevant_hits else 0.0)
            must_not_violation_values.append(1.0 if must_not_hits else 0.0)
            precision_values.append(len(relevant_hits) / k if k > 0 else 0.0)
            reciprocal_ranks.append(self._reciprocal_rank(hit_doc_ids, expected))

            for doc_id in hit_doc_ids:
                total_hits += 1
                entry = manifest_by_doc_id.get(doc_id, {})
                if entry.get("page_type") in {"atom", "synthesis", "principle"}:
                    compiled_hits += 1

            rows.append(
                {
                    "query": item.query,
                    "query_type": item.query_type,
                    "expected_doc_ids": item.expected_doc_ids,
                    "acceptable_doc_ids": item.acceptable_doc_ids,
                    "must_not_doc_ids": item.must_not_doc_ids,
                    "strict_recall_at_k": strict_recall_values[-1],
                    "loose_recall_at_k": loose_recall_values[-1],
                    "must_not_violation_at_k": must_not_violation_values[-1],
                    "precision_at_k": precision_values[-1],
                    "reciprocal_rank": reciprocal_ranks[-1],
                    "latency_ms": latency_ms,
                    "hits": [
                        {
                            "doc_id": hit.doc_id,
                            "score": hit.score,
                            "page_type": manifest_by_doc_id.get(hit.doc_id, {}).get("page_type"),
                        }
                        for hit in hits
                    ],
                    "must_not_hits": must_not_hits,
                    "notes": item.notes,
                }
            )

        report = {
            "query_count": len(queries),
            "k": k,
            "page_types": page_types or [],
            "metrics": {
                "strict_recall_at_k": self._avg(strict_recall_values),
                "loose_recall_at_k": self._avg(loose_recall_values),
                "must_not_violation_at_k": self._avg(must_not_violation_values),
                "precision_at_k": self._avg(precision_values),
                "mrr": self._avg(reciprocal_ranks),
                "compiled_hit_ratio": compiled_hits / total_hits if total_hits else 0.0,
            },
            "latency_ms": self._latency_summary(latencies),
            "queries": rows,
        }
        self._append_history(wiki_root=wiki_root, eval_file=eval_file, report=report)
        return report

    def _read_queries(self, eval_file: Path) -> list[RetrievalEvalQuery]:
        if not eval_file.exists():
            raise FileNotFoundError(f"eval file not found: {eval_file}")
        queries: list[RetrievalEvalQuery] = []
        for line_number, line in enumerate(eval_file.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                queries.append(RetrievalEvalQuery.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"invalid retrieval eval query at line {line_number}: {exc}") from exc
        return queries

    def _reciprocal_rank(self, hit_doc_ids: list[str], expected: set[str]) -> float:
        if not expected:
            return 0.0
        for index, doc_id in enumerate(hit_doc_ids, start=1):
            if doc_id in expected:
                return 1.0 / index
        return 0.0

    def _avg(self, values: list[float]) -> float:
        return round(mean(values), 6) if values else 0.0

    def _latency_summary(self, values: list[float]) -> dict[str, float]:
        if not values:
            return {"avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        ordered = sorted(values)
        return {
            "avg": round(mean(ordered), 3),
            "p50": self._percentile(ordered, 0.50),
            "p95": self._percentile(ordered, 0.95),
            "max": round(max(ordered), 3),
        }

    def _percentile(self, ordered: list[float], percentile: float) -> float:
        if not ordered:
            return 0.0
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
        return round(ordered[index], 3)

    def _append_history(self, wiki_root: Path, eval_file: Path, report: dict[str, Any]) -> None:
        runtime_root = wiki_root / ".agent-wiki"
        runtime_root.mkdir(exist_ok=True)
        history_path = runtime_root / "eval_history.jsonl"
        entry = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "eval_file": str(eval_file),
            "k": report.get("k", 5),
            "runtime_tuning": self._runtime_tuning_snapshot(runtime_root),
            "metrics": {
                "strict_recall_at_k": report["metrics"].get("strict_recall_at_k", 0.0),
                "loose_recall_at_k": report["metrics"].get("loose_recall_at_k", 0.0),
                "must_not_violation_at_k": report["metrics"].get("must_not_violation_at_k", 0.0),
                "mrr": report["metrics"].get("mrr", 0.0),
                "compiled_hit_ratio": report["metrics"].get("compiled_hit_ratio", 0.0),
            },
            "queries": report.get("queries", []),
        }
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _runtime_tuning_snapshot(self, runtime_root: Path) -> dict[str, Any] | str:
        tuning_path = runtime_root / "runtime_tuning.json"
        if not tuning_path.exists():
            return "defaults"
        try:
            return json.loads(tuning_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "defaults"
