from __future__ import annotations

import json
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
        queries = self._read_queries(eval_file)
        manifest = ManifestRepository(Path(wiki.workspace_path))
        manifest_by_doc_id = {
            str(entry.get("doc_id")): entry
            for entry in manifest.read_all()
            if entry.get("doc_id")
        }
        rows: list[dict[str, Any]] = []
        latencies: list[float] = []
        recall_values: list[float] = []
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
            )
            latency_ms = round(max(time.monotonic() - start, 0.0) * 1000, 3)
            latencies.append(latency_ms)
            hits = result.hits[:k]
            hit_doc_ids = [hit.doc_id for hit in hits]
            relevant = set(item.expected_doc_ids) | set(item.acceptable_doc_ids)
            expected = set(item.expected_doc_ids)
            relevant_hits = [doc_id for doc_id in hit_doc_ids if doc_id in relevant]
            expected_hits = [doc_id for doc_id in hit_doc_ids if doc_id in expected]

            recall_values.append(len(expected_hits) / len(expected) if expected else 0.0)
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
                    "recall_at_k": recall_values[-1],
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
                    "must_not_hits": [doc_id for doc_id in hit_doc_ids if doc_id in set(item.must_not_doc_ids)],
                    "notes": item.notes,
                }
            )

        return {
            "query_count": len(queries),
            "k": k,
            "page_types": page_types or [],
            "metrics": {
                "recall_at_k": self._avg(recall_values),
                "precision_at_k": self._avg(precision_values),
                "mrr": self._avg(reciprocal_ranks),
                "compiled_hit_ratio": compiled_hits / total_hits if total_hits else 0.0,
            },
            "latency_ms": self._latency_summary(latencies),
            "queries": rows,
        }

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
