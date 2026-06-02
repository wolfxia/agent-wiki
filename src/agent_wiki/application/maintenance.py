from __future__ import annotations
import json
from agent_wiki._compat import UTC
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from collections import Counter, defaultdict
import re
import yaml

from agent_wiki.application.claim_annotations import ClaimAnnotationService
from agent_wiki.application.compile_suggest import CompileSuggestService
from agent_wiki.application.diagnosis import DiagnosisService
from agent_wiki.application.eval_retrieval import EvalRetrievalService
from agent_wiki.application.fast_feedback import FastFeedbackService
from agent_wiki.application.relations import RelationsService
from agent_wiki.application.runtime_tuning import RuntimeTuningService
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.enums import Sensitivity
from agent_wiki.infrastructure.repair.raw_metadata_repair import RawMetadataRepairService
from agent_wiki.infrastructure.retrieval.knowledge_graph import KnowledgeGraphRepository
from agent_wiki.infrastructure.retrieval.embedding import SiliconFlowEmbeddingProvider
from agent_wiki.infrastructure.retrieval.index_consistency import IndexConsistencyChecker
from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository
from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository
from agent_wiki.infrastructure.retrieval.vector_index import SQLiteVectorIndexProvider
from agent_wiki.infrastructure.runtime.claim_annotations import ClaimAnnotationRepository
from agent_wiki.infrastructure.runtime.operation_log import OperationLogRepository
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository

_MAINTAIN_EVAL_TIMEOUT_SECONDS = 30


class MaintenanceService:
    def rebuild_index(self, wiki: WikiConfig, include_embedding: bool = False) -> dict[str, int]:
        wiki_root = Path(wiki.workspace_path)
        manifest_entries = ManifestRepository(wiki_root).read_all()
        manifest_doc_ids = {
            str(entry.get("doc_id"))
            for entry in manifest_entries
            if entry.get("doc_id")
        }

        retrieval_path = wiki_root / "retrieval_index.jsonl"
        removed_count = 0
        if retrieval_path.exists():
            for line in retrieval_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                card = json.loads(line)
                doc_id = card.get("doc_id")
                if doc_id and str(doc_id) not in manifest_doc_ids:
                    removed_count += 1

        RetrievalIndexRepository(wiki_root).rebuild_from_manifest(manifest_entries)
        SQLiteFTSIndexProvider(wiki_root, wiki_id=wiki.wiki_id).rebuild_from_manifest(manifest_entries)
        embedded_count = 0
        if include_embedding:
            vector_provider = SQLiteVectorIndexProvider(wiki_root, wiki_id=wiki.wiki_id)
            embedding_provider = self._embedding_provider_from_wiki(wiki)
            embedded_count = vector_provider.rebuild_from_manifest(manifest_entries, embedding_provider=embedding_provider)
        return {"removed_count": removed_count, "rebuilt_count": len(manifest_doc_ids), "embedded_count": embedded_count}

    def _embedding_provider_from_wiki(self, wiki: WikiConfig):
        config = wiki.retrieval.embedding
        if config is None:
            return None
        if "embedding" not in set(wiki.retrieval.optional_providers or []):
            return None
        if config.provider != "siliconflow":
            return None
        return SiliconFlowEmbeddingProvider(
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            model=config.model,
            dimension=config.dimension,
            batch_size=config.batch_size,
            timeout_seconds=config.timeout_seconds,
        )

    def _embed_incremental(self, wiki_root: Path, wiki: WikiConfig) -> dict[str, int]:
        embedding_provider = self._embedding_provider_from_wiki(wiki)
        if embedding_provider is None:
            return {"embedded_count": 0}

        state_path = wiki_root / ".agent-wiki" / "vector_index_state.json"
        state = self._read_json_dict(state_path)
        manifest_entries = ManifestRepository(wiki_root).read_all()
        vector_index = SQLiteVectorIndexProvider(
            wiki_root,
            wiki_id=wiki.wiki_id,
            dimension=wiki.retrieval.embedding.dimension if wiki.retrieval.embedding is not None else 1024,
        )

        embedded_count = 0
        for entry in manifest_entries:
            doc_id = str(entry.get("doc_id") or "")
            canonical_uri = str(entry.get("canonical_uri") or "")
            updated_at = str(entry.get("updated_at") or "")
            if not doc_id or not canonical_uri or state.get(doc_id) == updated_at:
                continue
            page_path = wiki_root / canonical_uri
            if not page_path.exists() or not page_path.is_file():
                continue

            content = self._embedding_content(page_path.read_text(encoding="utf-8"))
            try:
                embeddings = embedding_provider.embed_texts([content])
            except Exception:
                continue
            if not embeddings:
                continue
            embedding = embeddings[0]
            vector_index.upsert(
                doc_id,
                {
                    "wiki_id": entry.get("wiki_id") or wiki.wiki_id,
                    "page_type": entry.get("page_type") or "",
                    "embedding": embedding,
                    "updated_at": updated_at,
                },
            )
            state[doc_id] = updated_at
            embedded_count += 1

        if embedded_count > 0 or not state_path.exists():
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"embedded_count": embedded_count}

    def _embedding_content(self, content: str) -> str:
        tokens = content.split()
        return " ".join(tokens[:512]) if tokens else content[:4096]

    def _read_json_dict(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def run(self, wiki: WikiConfig, auto_tune: bool = False) -> dict:
        wiki_root = Path(wiki.workspace_path)
        queue_timeouts_recovered = ReviewQueueRepository(wiki_root).recover_assigned_timeouts()
        repair_summary = RawMetadataRepairService().repair(wiki)
        orphan_cleanup_count = self._clean_orphan_authority_entries(wiki)
        compiled_metadata_repairs = self._repair_compiled_metadata_from_page_frontmatter(wiki_root)
        index_rebuild = self._repair_runtime_indexes_if_needed(
            wiki,
            force_rebuild=compiled_metadata_repairs > 0,
        )
        compile_candidates = CompileSuggestService().detect_and_enqueue(wiki)
        quality_signals = FastFeedbackService().detect_and_enqueue(wiki)
        graph_repository = KnowledgeGraphRepository(wiki_root, wiki_id=wiki.wiki_id)
        typed_relations = graph_repository.rebuild_from_raw_pages()
        graph_repository.backfill_confidence_labels()
        relation_reviews = graph_repository.enqueue_ambiguous_reviews(ReviewQueueRepository(wiki_root))
        relations = RelationsService()
        co_occurrences = relations.detect_and_enqueue_co_occurrences(wiki)
        cross_references = relations.detect_and_enqueue_cross_references(wiki)
        duplicate_atom_warnings = self._detect_duplicate_atom_warnings(wiki)
        claim_annotations = ClaimAnnotationService().annotate_incremental(wiki_root, limit=50)
        embedding_maintenance = self._embed_incremental(wiki_root, wiki)

        metadata_repair_candidates = [c for c in compile_candidates if c["kind"] == "needs_metadata_repair"]
        compile_suggestions = [c for c in compile_candidates if c["kind"] != "needs_metadata_repair"]

        action_items: list[str] = []
        total_repair_candidates = repair_summary["metadata_repair_candidates"] + len(metadata_repair_candidates)
        if total_repair_candidates:
            action_items.append(
                f"Repair raw metadata for {total_repair_candidates} imported raw pages"
            )
        action_items.extend(self._compile_action_items(compile_suggestions))
        for signal in quality_signals:
            action_items.append(
                f"Investigate repeated zero-hit query: {signal['query']} ({signal['zero_hit_count']} misses)"
            )
        for relation in co_occurrences:
            action_items.append(
                f"Review co-occurrence candidate: {relation['doc_ids'][0]} <-> {relation['doc_ids'][1]}"
            )
        for relation in cross_references:
            action_items.append(
                f"Review cross-reference candidate: {relation['doc_ids'][0]} <-> {relation['doc_ids'][1]}"
            )

        summary = {
            "metadata_repair_candidates": total_repair_candidates,
            "orphan_cleanup_count": orphan_cleanup_count,
            "queue_timeouts_recovered": queue_timeouts_recovered,
            "compiled_metadata_repairs": compiled_metadata_repairs,
            "index_rebuild": index_rebuild,
            "compile_suggestions": len(compile_suggestions),
            "typed_relations": typed_relations,
            "relation_reviews": relation_reviews,
            "quality_signals": len(quality_signals),
            "co_occurrence_candidates": len(co_occurrences),
            "cross_reference_candidates": len(cross_references),
            "duplicate_atom_warnings": duplicate_atom_warnings,
            "claim_annotations": claim_annotations,
            "embedding_maintenance": embedding_maintenance,
            "compile_strategy_counts": self._compile_strategy_counts(compile_suggestions),
            "quality_metrics": self._quality_metrics(wiki_root),
            "value_metrics": self._value_metrics(wiki_root),
            "staleness_governance": self._staleness_governance(wiki),
            "action_items": action_items,
        }
        for warning in self._duplicate_warning_action_items(wiki_root):
            summary["action_items"].append(warning)
        self._run_eval_if_available(wiki, summary)
        if auto_tune:
            summary["auto_tune"] = RuntimeTuningService().auto_tune(
                wiki,
                DiagnosisService().analyze(wiki),
                evaluate_after=lambda: self._run_eval_report_if_available(wiki),
            )
        else:
            summary["auto_tune"] = {"status": "disabled"}
        return summary

    def _repair_runtime_indexes_if_needed(self, wiki: WikiConfig, force_rebuild: bool = False) -> dict:
        wiki_root = Path(wiki.workspace_path)
        issues = IndexConsistencyChecker().check(wiki_root)
        actionable = [
            issue for issue in issues
            if issue.startswith("retrieval index missing manifest entry:")
            or issue.startswith("retrieval index entry without manifest entry:")
            or issue.startswith("fts index missing manifest entry:")
            or issue.startswith("fts index entry without manifest entry:")
        ]
        if force_rebuild and not actionable:
            rebuilt = self.rebuild_index(wiki, include_embedding=False)
            return {
                **rebuilt,
                "reason": "compiled_metadata_repair",
                "issues_detected": 0,
            }
        if not actionable:
            return {"rebuilt_count": 0, "removed_count": 0, "embedded_count": 0, "reason": None}
        rebuilt = self.rebuild_index(wiki, include_embedding=False)
        return {
            **rebuilt,
            "reason": "index_inconsistency",
            "issues_detected": len(actionable),
        }

    def _repair_compiled_metadata_from_page_frontmatter(self, wiki_root: Path) -> int:
        manifest = ManifestRepository(wiki_root)
        repairs: list[dict] = []
        for entry in manifest.read_all():
            if str(entry.get("page_type") or "") not in {"atom", "synthesis", "principle"}:
                continue
            if self._compiled_metadata_present(entry):
                continue
            frontmatter = self._page_frontmatter(wiki_root, entry)
            if not frontmatter:
                continue
            patch = self._compiled_metadata_patch(entry, frontmatter)
            if patch:
                repairs.append({"doc_id": entry.get("doc_id"), **patch})
        manifest.batch_upsert(repairs)
        return len(repairs)

    def _compiled_metadata_present(self, entry: dict) -> bool:
        return bool(entry.get("aliases")) and bool(entry.get("confidence")) and bool(entry.get("wikilinks")) and bool(entry.get("sensitivity"))

    def _compiled_metadata_patch(self, entry: dict, frontmatter: dict) -> dict:
        patch: dict[str, object] = {}
        aliases = entry.get("aliases")
        if not aliases:
            frontmatter_aliases = self._frontmatter_list(frontmatter.get("aliases"))
            if frontmatter_aliases:
                patch["aliases"] = frontmatter_aliases
        confidence = str(entry.get("confidence") or "").strip()
        if not confidence:
            frontmatter_confidence = str(frontmatter.get("confidence") or "").strip()
            if frontmatter_confidence:
                patch["confidence"] = frontmatter_confidence
        wikilinks = entry.get("wikilinks")
        if not wikilinks:
            frontmatter_wikilinks = self._frontmatter_list(frontmatter.get("wikilinks"))
            if frontmatter_wikilinks:
                patch["wikilinks"] = frontmatter_wikilinks
        sensitivity = str(entry.get("sensitivity") or "").strip()
        if not sensitivity:
            frontmatter_sensitivity = self._normalize_sensitivity(frontmatter.get("sensitivity"))
            if frontmatter_sensitivity:
                patch["sensitivity"] = frontmatter_sensitivity
        return patch

    def _page_frontmatter(self, wiki_root: Path, entry: dict) -> dict:
        canonical_uri = entry.get("canonical_uri")
        if not canonical_uri:
            return {}
        page_path = wiki_root / str(canonical_uri)
        if not page_path.exists() or not page_path.is_file():
            return {}
        content = page_path.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n?", content, flags=re.DOTALL)
        if match is None:
            return {}
        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            return {}
        return frontmatter if isinstance(frontmatter, dict) else {}

    def _frontmatter_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized

    def _normalize_sensitivity(self, value: object) -> str | None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        if normalized == "normal":
            return Sensitivity.INTERNAL.value
        if normalized in {member.value for member in Sensitivity}:
            return normalized
        return None

    def _clean_orphan_authority_entries(self, wiki: WikiConfig) -> int:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        topic_index = TopicIndexRepository(wiki_root)
        retrieval_index = RetrievalIndexRepository(wiki_root)
        fts_index = SQLiteFTSIndexProvider(wiki_root, wiki_id=wiki.wiki_id)
        operation_log = OperationLogRepository(wiki_root)

        orphan_doc_ids: list[str] = []
        for entry in manifest.read_all():
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                orphan_doc_ids.append(str(entry.get("doc_id", "")))
                continue
            page_path = wiki_root / str(canonical_uri)
            if not page_path.exists() or not page_path.is_file():
                orphan_doc_ids.append(str(entry.get("doc_id", "")))

        for doc_id in orphan_doc_ids:
            if not doc_id:
                continue
            manifest.delete(doc_id)
            topic_index.delete(doc_id)
            fts_index.delete(doc_id)
            operation_log.append({
                "operation": "orphan_cleanup",
                "wiki_id": wiki.wiki_id,
                "doc_id": doc_id,
            })

        if orphan_doc_ids:
            remaining_entries = manifest.read_all()
            retrieval_index.rebuild_from_manifest(remaining_entries)
            fts_index.rebuild_from_manifest(remaining_entries)

        return len([doc_id for doc_id in orphan_doc_ids if doc_id])

    def _run_eval_if_available(self, wiki: WikiConfig, summary: dict) -> None:
        try:
            report = self._run_eval_report_if_available(wiki)
        except FuturesTimeoutError:
            summary["eval_timeout"] = True
            return
        if report is not None:
            summary["eval_baseline"] = report

    def _run_eval_report_if_available(self, wiki: WikiConfig) -> dict | None:
        eval_file = self._resolve_eval_file(wiki)
        if not eval_file.exists():
            return None
        actor = ResolvedActor(actor_type="agent", actor_id="system-maintenance", transport="maintenance")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                EvalRetrievalService().run,
                wiki=wiki,
                actor=actor,
                eval_file=eval_file,
                k=5,
                page_types=None,
            )
            try:
                return future.result(timeout=_MAINTAIN_EVAL_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                raise

    def _resolve_eval_file(self, wiki: WikiConfig) -> Path:
        wiki_root = Path(wiki.workspace_path)
        workspace_eval = wiki_root / "eval" / "retrieval_queries.jsonl"
        if workspace_eval.exists():
            return workspace_eval
        repo_eval = Path(__file__).resolve().parents[3] / "eval" / "retrieval_queries.jsonl"
        return repo_eval

    def _detect_duplicate_atom_warnings(self, wiki: WikiConfig) -> int:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        atoms_by_cluster: defaultdict[tuple[str, str], list[dict]] = defaultdict(list)
        for entry in manifest.read_all():
            if entry.get("page_type") != "atom":
                continue
            summary = str(entry.get("summary") or "").strip()
            topic = str(entry.get("topic") or "").strip()
            problem_cluster = str(entry.get("problem_cluster") or "").strip()
            if not summary or not topic or not problem_cluster:
                continue
            atoms_by_cluster[(topic, problem_cluster)].append(entry)

        queue_entries: list[dict] = []
        for (topic, problem_cluster), atoms in atoms_by_cluster.items():
            for left_index in range(len(atoms)):
                for right_index in range(left_index + 1, len(atoms)):
                    left = atoms[left_index]
                    right = atoms[right_index]
                    similarity = self._summary_jaccard(
                        str(left.get("summary") or ""),
                        str(right.get("summary") or ""),
                    )
                    if similarity <= 0.8:
                        continue
                    doc_ids = sorted([str(left.get("doc_id") or ""), str(right.get("doc_id") or "")])
                    queue_entries.append(
                        {
                            "item_id": f"duplicate_atom_warning:{topic}:{problem_cluster}:{doc_ids[0]}:{doc_ids[1]}",
                            "item_type": "duplicate_atom_warning",
                            "doc_id": doc_ids[0],
                            "topic": topic,
                            "problem_cluster": problem_cluster,
                            "content_state": {
                                "doc_ids": doc_ids,
                                "similarity": round(similarity, 3),
                            },
                            "reason": "near-duplicate atom summaries in the same cluster",
                            "status": "open",
                        }
                    )
        return ReviewQueueRepository(wiki_root).append_many(queue_entries)

    def _summary_jaccard(self, left: str, right: str) -> float:
        left_tokens = self._summary_tokens(left)
        right_tokens = self._summary_tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return intersection / union if union else 0.0

    def _summary_tokens(self, value: str) -> set[str]:
        return {token for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", value.lower()) if token}

    def _duplicate_warning_action_items(self, wiki_root: Path) -> list[str]:
        queue = ReviewQueueRepository(wiki_root)
        actions: list[str] = []
        for item in queue.read_all():
            if item.get("item_type") != "duplicate_atom_warning" or item.get("status") != "open":
                continue
            doc_ids = (item.get("content_state") or {}).get("doc_ids") or []
            if len(doc_ids) < 2:
                continue
            actions.append(f"Review duplicate atom warning: {doc_ids[0]} <-> {doc_ids[1]}")
        return actions

    def _compile_action_items(self, compile_suggestions: list[dict]) -> list[str]:
        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for candidate in compile_suggestions:
            key = (str(candidate.get("topic") or ""), str(candidate.get("problem_cluster") or ""))
            summary = grouped.get(key)
            if summary is None:
                summary = {
                    "topic": key[0],
                    "problem_cluster": key[1],
                    "subclusters": 0,
                    "raw_pages": 0,
                    "strategy": "Light",
                    "max_priority_score": 0,
                }
                grouped[key] = summary
            summary["subclusters"] = int(summary["subclusters"]) + 1
            summary["raw_pages"] = int(summary["raw_pages"]) + int(candidate.get("raw_count", 0))
            summary["strategy"] = self._max_compile_strategy(
                str(summary["strategy"]),
                str(candidate.get("compile_strategy") or "Light"),
            )
            summary["max_priority_score"] = max(
                int(summary["max_priority_score"]),
                int(candidate.get("compile_priority_score", 0)),
            )

        ordered_groups = sorted(
            grouped.values(),
            key=lambda summary: (
                -int(summary["max_priority_score"]),
                -self._compile_strategy_rank(str(summary["strategy"])),
                -int(summary["raw_pages"]),
                str(summary["topic"]),
                str(summary["problem_cluster"]),
            ),
        )
        return [
            (
                f"Compile cluster {summary['topic']}/{summary['problem_cluster']} "
                f"across {summary['subclusters']} subclusters "
                f"({summary['raw_pages']} raw pages, strategy {summary['strategy']})"
            )
            for summary in ordered_groups
        ]

    def _max_compile_strategy(self, left: str, right: str) -> str:
        return left if self._compile_strategy_rank(left) >= self._compile_strategy_rank(right) else right

    def _compile_strategy_rank(self, strategy: str) -> int:
        order = {"Light": 0, "Standard": 1, "Deep": 2}
        return order.get(strategy, 0)

    def _compile_strategy_counts(self, compile_suggestions: list[dict]) -> dict[str, int]:
        counts = {"Light": 0, "Standard": 0, "Deep": 0}
        for candidate in compile_suggestions:
            strategy = str(candidate.get("compile_strategy") or "Standard")
            counts[strategy] = counts.get(strategy, 0) + 1
        return counts

    def _parse_timestamp(self, value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _quality_metrics(self, wiki_root: Path) -> dict:
        manifest_entries = ManifestRepository(wiki_root).read_all()
        queue_entries = ReviewQueueRepository(wiki_root).read_all()
        annotation_entries = ClaimAnnotationRepository(wiki_root).read_all()

        compile_pending = sum(
            1
            for item in queue_entries
            if item.get("item_type") == "compile_suggestion" and item.get("status", "open") == "open"
        )

        raw_doc_ids = {
            str(entry.get("doc_id"))
            for entry in manifest_entries
            if entry.get("page_type") == "raw" and entry.get("doc_id")
        }
        atom_doc_ids = {
            str(entry.get("doc_id"))
            for entry in manifest_entries
            if entry.get("page_type") == "atom" and entry.get("doc_id")
        }
        referenced_raw_doc_ids: set[str] = set()
        synthesis_topics: set[str] = set()
        freshness_distribution = {"recent": 0, "fresh": 0, "stale": 0}
        now = datetime.now(UTC)

        for entry in manifest_entries:
            if entry.get("page_type") == "atom":
                for ref in entry.get("source_refs") or []:
                    _, _, doc_id = str(ref).partition(":")
                    if doc_id:
                        referenced_raw_doc_ids.add(doc_id)
            if entry.get("page_type") == "synthesis":
                topic = str(entry.get("topic") or "").strip()
                if topic:
                    synthesis_topics.add(topic)
            if entry.get("page_type") in {"atom", "synthesis"}:
                created_or_updated_at = self._parse_timestamp(
                    entry.get("created_at") or entry.get("updated_at") or entry.get("updated")
                )
                if created_or_updated_at is None:
                    freshness_distribution["stale"] += 1
                    continue
                age_days = max((now - created_or_updated_at).days, 0)
                if age_days <= 7:
                    freshness_distribution["recent"] += 1
                elif age_days <= 30:
                    freshness_distribution["fresh"] += 1
                else:
                    freshness_distribution["stale"] += 1

        compile_coverage = len(raw_doc_ids & referenced_raw_doc_ids) / len(raw_doc_ids) if raw_doc_ids else 0.0
        annotated_atom_doc_ids = {
            str(entry.get("doc_id"))
            for entry in annotation_entries
            if entry.get("doc_id")
        }
        claim_annotation_coverage = len(atom_doc_ids & annotated_atom_doc_ids) / len(atom_doc_ids) if atom_doc_ids else 0.0

        return {
            "compile_pending": compile_pending,
            "compile_coverage": round(compile_coverage, 3),
            "freshness_distribution": freshness_distribution,
            "synthesis_directions": len(synthesis_topics),
            "claim_annotation_coverage": round(claim_annotation_coverage, 3),
        }

    def _value_metrics(self, wiki_root: Path) -> dict:
        eval_history = self._read_jsonl(wiki_root / ".agent-wiki" / "eval_history.jsonl")
        post_compile_query_uplift = 0.0
        if len(eval_history) >= 2:
            previous = eval_history[-2].get("metrics") or {}
            latest = eval_history[-1].get("metrics") or {}
            post_compile_query_uplift = round(
                float(latest.get("strict_recall_at_k", 0.0) or 0.0)
                - float(previous.get("strict_recall_at_k", 0.0) or 0.0),
                3,
            )

        manifest = ManifestRepository(wiki_root)
        atom_doc_ids = {str(entry.get("doc_id")) for entry in manifest.read_all() if entry.get("page_type") == "atom" and entry.get("doc_id")}
        referenced_atoms: set[str] = set()
        for entry in self._read_jsonl(wiki_root / "query_outcomes.jsonl"):
            if entry.get("record_type") == "feedback" or "query" not in entry or "hit_count" not in entry:
                continue
            for doc_id in entry.get("accepted_doc_ids") or []:
                doc_id = str(doc_id)
                if doc_id in atom_doc_ids:
                    referenced_atoms.add(doc_id)
            for item in entry.get("score_breakdown") or []:
                doc_id = str(item.get("doc_id") or "")
                if doc_id in atom_doc_ids:
                    referenced_atoms.add(doc_id)
        atom_reference_rate = round(len(referenced_atoms) / len(atom_doc_ids), 3) if atom_doc_ids else 0.0
        return {
            "post_compile_query_uplift": post_compile_query_uplift,
            "atom_reference_rate": atom_reference_rate,
        }

    def _staleness_governance(self, wiki: WikiConfig) -> dict:
        wiki_root = Path(wiki.workspace_path)
        hot_doc_counts = self._accepted_doc_counts(wiki_root)
        if not hot_doc_counts:
            return {"hot_stale_doc_ids": [], "queued_refreshes": 0}
        staleness_days = int(getattr(wiki.dream_cycle.quality, "staleness_days", 30))
        cutoff = datetime.now(UTC) - timedelta(days=staleness_days)
        manifest = ManifestRepository(wiki_root)
        hot_stale_doc_ids: list[str] = []
        for doc_id, count in hot_doc_counts.items():
            if count < 3:
                continue
            entry = manifest.find(doc_id)
            if not entry or entry.get("page_type") not in {"atom", "synthesis"}:
                continue
            if not self._is_stale(entry.get("updated_at") or entry.get("updated"), cutoff):
                continue
            hot_stale_doc_ids.append(doc_id)
        hot_stale_doc_ids.sort()
        queue_entries = []
        for doc_id in hot_stale_doc_ids:
            entry = manifest.find(doc_id) or {}
            queue_entries.append(
                {
                    "item_id": f"staleness_refresh:{doc_id}",
                    "item_type": "staleness_refresh",
                    "doc_id": doc_id,
                    "topic": entry.get("topic"),
                    "problem_cluster": entry.get("problem_cluster"),
                    "reason": "hot compiled page is stale and should be refreshed",
                    "content_state": {
                        "accepted_count": hot_doc_counts[doc_id],
                        "staleness_days": staleness_days,
                    },
                    "status": "open",
                }
            )
        queued = ReviewQueueRepository(wiki_root).append_many(queue_entries)
        return {"hot_stale_doc_ids": hot_stale_doc_ids, "queued_refreshes": queued}

    def _accepted_doc_counts(self, wiki_root: Path) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for entry in self._read_jsonl(wiki_root / "query_outcomes.jsonl"):
            if entry.get("record_type") == "feedback" or "query" not in entry or "hit_count" not in entry:
                continue
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

    def _read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
