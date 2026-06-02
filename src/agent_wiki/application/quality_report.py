from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.enums import PageType
from agent_wiki.infrastructure.retrieval.knowledge_graph import CONFIDENCE_AMBIGUOUS, CONFIDENCE_EXTRACTED, CONFIDENCE_INFERRED
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository

_COMPILED_PAGE_TYPES = {PageType.ATOM.value, PageType.SYNTHESIS.value, PageType.PRINCIPLE.value}


class QualityReportService:
    def generate(self, wiki: WikiConfig) -> dict:
        wiki_root = Path(wiki.workspace_path)

        query_count, hit_rate = self._query_metrics(wiki_root)
        manifest = ManifestRepository(wiki_root)
        entries = manifest.read_all()
        raw_count, compiled_count = self._page_counts(entries)
        compile_rate = (compiled_count / raw_count) if raw_count else 0.0
        orphan_count = self._orphan_count(entries)
        compile_failure_rate, compile_failure_breakdown, avg_compile_latency_seconds = self._compile_attempt_metrics(wiki_root)
        atom_field_completeness = self._metadata_completeness(entries)
        section_structure_compliance = self._section_structure_compliance(wiki_root, entries)
        source_ref_coverage = self._source_ref_coverage(entries)
        cluster_coverage, mature_cluster_coverage = self._cluster_coverage(entries)
        relation_stats = self._relation_stats(wiki_root)
        eval_baseline = self._latest_eval_baseline(wiki_root)

        return {
            "query_count": query_count,
            "hit_rate": hit_rate,
            "raw_count": raw_count,
            "compiled_count": compiled_count,
            "compile_rate": compile_rate,
            "orphan_count": orphan_count,
            "compile_failure_rate": compile_failure_rate,
            "compile_failure_breakdown": compile_failure_breakdown,
            "avg_compile_latency_seconds": avg_compile_latency_seconds,
            "atom_field_completeness": atom_field_completeness,
            "section_structure_compliance": section_structure_compliance,
            "source_ref_coverage": source_ref_coverage,
            "cluster_coverage": cluster_coverage,
            "mature_cluster_coverage": mature_cluster_coverage,
            "relation_stats": relation_stats,
            "eval_baseline": eval_baseline,
        }

    def _query_metrics(self, wiki_root: Path) -> tuple[int, float]:
        outcomes_path = wiki_root / "query_outcomes.jsonl"
        if not outcomes_path.exists():
            return 0, 0.0
        total = 0
        hits = 0
        for line in outcomes_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("record_type") == "feedback" or "query" not in entry or "hit_count" not in entry:
                continue
            total += 1
            if entry.get("hit_count", 0) > 0:
                hits += 1
        if total == 0:
            return 0, 0.0
        return total, hits / total

    def _page_counts(self, entries: list[dict]) -> tuple[int, int]:
        raw = 0
        compiled = 0
        for entry in entries:
            page_type = entry.get("page_type")
            if page_type == "raw":
                raw += 1
            elif page_type in _COMPILED_PAGE_TYPES:
                compiled += 1
        return raw, compiled

    def _orphan_count(self, entries: list[dict]) -> int:
        referenced: set[str] = set()
        for entry in entries:
            for ref in entry.get("source_refs") or []:
                _, _, doc_id = ref.partition(":")
                if doc_id:
                    referenced.add(doc_id)
        orphans = 0
        for entry in entries:
            doc_id = entry.get("doc_id")
            if not doc_id:
                continue
            if doc_id not in referenced:
                orphans += 1
        return orphans

    def _compile_attempt_metrics(self, wiki_root: Path) -> tuple[float, dict[str, int], float]:
        queue_path = wiki_root / "review_queue.jsonl"
        if not queue_path.exists():
            return 0.0, {}, 0.0
        resolved = 0
        failed = 0
        failure_breakdown: Counter[str] = Counter()
        latencies: list[float] = []
        for line in queue_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("item_type") != "compile_suggestion":
                continue
            status = item.get("status")
            if status == "resolved":
                resolved += 1
            elif status == "failed":
                failed += 1
                error_type = (item.get("content_state") or {}).get("error_type") or "unknown"
                failure_breakdown[str(error_type)] += 1
            else:
                continue
            latency = (item.get("content_state") or {}).get("latency_seconds")
            if isinstance(latency, int | float):
                latencies.append(float(latency))
        attempted = resolved + failed
        failure_rate = (failed / attempted) if attempted else 0.0
        avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
        return failure_rate, dict(failure_breakdown), avg_latency

    def _metadata_completeness(self, entries: list[dict]) -> float:
        compiled_entries = [entry for entry in entries if entry.get("page_type") in _COMPILED_PAGE_TYPES]
        if not compiled_entries:
            return 0.0
        complete = 0
        required_fields = ("summary", "aliases", "confidence", "wikilinks")
        for entry in compiled_entries:
            if all(bool(entry.get(field)) for field in required_fields):
                complete += 1
        return complete / len(compiled_entries)

    def _section_structure_compliance(self, wiki_root: Path, entries: list[dict]) -> float:
        atom_entries = [entry for entry in entries if entry.get("page_type") == PageType.ATOM.value]
        if not atom_entries:
            return 0.0
        compliant = 0
        for entry in atom_entries:
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                continue
            page_path = wiki_root / str(canonical_uri)
            if not page_path.exists():
                continue
            content = page_path.read_text(encoding="utf-8")
            if "claims" in content.lower() and "evidence" in content.lower():
                compliant += 1
        return compliant / len(atom_entries)

    def _source_ref_coverage(self, entries: list[dict]) -> float:
        compiled_entries = [entry for entry in entries if entry.get("page_type") in _COMPILED_PAGE_TYPES]
        if not compiled_entries:
            return 0.0
        covered = sum(1 for entry in compiled_entries if entry.get("source_refs"))
        return covered / len(compiled_entries)

    def _cluster_coverage(self, entries: list[dict]) -> tuple[float, float]:
        raw_clusters: Counter[tuple[str, str]] = Counter()
        compiled_clusters: set[tuple[str, str]] = set()
        for entry in entries:
            topic = str(entry.get("topic") or "")
            problem_cluster = str(entry.get("problem_cluster") or "")
            if not topic or not problem_cluster:
                continue
            key = (topic, problem_cluster)
            if entry.get("page_type") == PageType.RAW.value:
                raw_clusters[key] += 1
            elif entry.get("page_type") in _COMPILED_PAGE_TYPES:
                compiled_clusters.add(key)

        if not raw_clusters:
            return 0.0, 0.0
        covered_clusters = sum(1 for key in raw_clusters if key in compiled_clusters)
        mature_clusters = [key for key, count in raw_clusters.items() if count >= 3]
        mature_covered = sum(1 for key in mature_clusters if key in compiled_clusters)
        mature_coverage = (mature_covered / len(mature_clusters)) if mature_clusters else 0.0
        return covered_clusters / len(raw_clusters), mature_coverage

    def _relation_stats(self, wiki_root: Path) -> dict[str, int]:
        graph_path = wiki_root / "knowledge_graph.jsonl"
        queue_path = wiki_root / "review_queue.jsonl"
        stats = {
            "total": 0,
            "extracted": 0,
            "inferred": 0,
            "ambiguous": 0,
            "pending_review": 0,
        }
        if graph_path.exists():
            for line in graph_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                stats["total"] += 1
                label = str(entry.get("confidence_label") or CONFIDENCE_INFERRED).upper()
                if label == CONFIDENCE_EXTRACTED:
                    stats["extracted"] += 1
                elif label == CONFIDENCE_AMBIGUOUS:
                    stats["ambiguous"] += 1
                else:
                    stats["inferred"] += 1
        if queue_path.exists():
            for line in queue_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("item_type") == "relation_review" and item.get("status", "open") == "open":
                    stats["pending_review"] += 1
        return stats

    def _latest_eval_baseline(self, wiki_root: Path) -> dict | None:
        history_path = wiki_root / ".agent-wiki" / "eval_history.jsonl"
        if not history_path.exists():
            return None
        lines = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
