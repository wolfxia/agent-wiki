import json
from collections import defaultdict
from agent_wiki._compat import UTC
from datetime import datetime
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.doc_id import slugify_doc_id
from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository
from agent_wiki.infrastructure.storage.purpose_reader import PurposeReader

RAW_ACCUMULATION_THRESHOLD = 3
SUB_CLUSTER_SIZE = 3


class CompileSuggestService:
    def detect(self, wiki: WikiConfig, threshold: int = RAW_ACCUMULATION_THRESHOLD) -> list[dict]:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        pending = PendingStateRepository(wiki_root)
        purpose_reader = PurposeReader(wiki_root)
        purpose = purpose_reader.read()
        entries = manifest.read_all()

        candidates: list[dict] = []
        candidates.extend(self._metadata_repair_candidates(entries, pending))

        raw_cluster_entries: dict[tuple[str, str], list[dict]] = defaultdict(list)
        compiled_cluster_counts: dict[tuple[str, str], int] = defaultdict(int)
        for entry in entries:
            page_type = entry.get("page_type")
            topic = entry.get("topic") or ""
            problem_cluster = entry.get("problem_cluster") or ""
            if page_type == "raw":
                if topic and problem_cluster:
                    raw_cluster_entries[(topic, problem_cluster)].append(entry)
                continue
            if topic and problem_cluster:
                compiled_cluster_counts[(topic, problem_cluster)] += 1

        query_signal_counts = self._query_signal_counts(wiki_root, set(raw_cluster_entries.keys()))
        quality_failure_counts = self._quality_failure_counts(wiki_root)
        eval_failure_counts = self._eval_failure_counts(wiki_root, entries)

        for (topic, problem_cluster), raw_entries in raw_cluster_entries.items():
            raw_entries.sort(key=lambda entry: str(entry.get("doc_id") or ""))
            count = len(raw_entries)
            if count < threshold:
                continue
            compiled_count = compiled_cluster_counts.get((topic, problem_cluster), 0)
            cluster_key = (topic, problem_cluster)
            purpose_aligned = purpose_reader.is_aligned(topic)
            priority_score = self._compile_priority_score(
                raw_count=count,
                query_hit_frequency=query_signal_counts[cluster_key]["hits"],
                query_miss_frequency=query_signal_counts[cluster_key]["misses"],
                purpose_aligned=purpose_aligned,
                existing_compiled_count=compiled_count,
                previous_quality_gate_failures=quality_failure_counts[cluster_key],
                eval_failure_frequency=eval_failure_counts[cluster_key],
                staleness_days=self._cluster_staleness_days(raw_entries),
                contradiction_markers_present=self._has_contradiction_markers(wiki_root, raw_entries),
            )
            compile_strategy = self._compile_strategy(priority_score)
            for sub_cluster_index, group in enumerate(self._chunks(raw_entries, SUB_CLUSTER_SIZE), start=1):
                raw_doc_ids = [str(entry.get("doc_id")) for entry in group if entry.get("doc_id")]
                candidates.append({
                    "kind": "undercompiled_cluster" if compiled_count == 0 else "ready_to_compile",
                    "topic": topic,
                    "problem_cluster": problem_cluster,
                    "raw_count": len(raw_doc_ids),
                    "cluster_raw_count": count,
                    "compiled_count": compiled_count,
                    "sub_cluster_index": sub_cluster_index,
                    "sub_cluster_id": self._sub_cluster_id(topic, problem_cluster, sub_cluster_index),
                    "raw_doc_ids": raw_doc_ids,
                    "purpose_aligned": purpose_aligned,
                    "compile_priority_score": priority_score,
                    "compile_strategy": compile_strategy,
                    "deep_compile_rounds": 3 if compile_strategy == "Deep" else 1,
                    "priority": 0 if self._topic_matches_p0(topic, purpose) else 1,
                    "priority_label": "P0" if self._topic_matches_p0(topic, purpose) else "P1",
                    "priority_reason": "purpose_aligned" if self._topic_matches_p0(topic, purpose) else "general",
                })

        candidates.sort(key=self._candidate_sort_key)
        return candidates

    def detect_and_enqueue(self, wiki: WikiConfig, threshold: int = RAW_ACCUMULATION_THRESHOLD) -> list[dict]:
        candidates = self.detect(wiki, threshold)
        if not candidates:
            return candidates

        wiki_root = Path(wiki.workspace_path)
        queue = ReviewQueueRepository(wiki_root)
        queue.remove_old_format_compile_suggestions()
        queue_items = queue.read_all()
        queue_by_id = {str(item.get("item_id")): item for item in queue_items if item.get("item_id")}
        metadata_repair_entries: list[dict] = []
        compile_suggestion_entries: list[dict] = []
        active_candidates: list[dict] = []
        for candidate in candidates:
            if candidate["kind"] == "needs_metadata_repair":
                active_candidates.append(candidate)
                metadata_repair_entries.append(
                    {
                        "item_id": f"metadata_repair:{candidate['doc_id']}",
                        "item_type": "metadata_repair",
                        "doc_id": candidate["doc_id"],
                        "reason": candidate.get("reason", "missing metadata"),
                        "status": "open",
                    }
                )
                continue

            entry = self._compile_suggestion_entry(candidate)
            existing = queue_by_id.get(str(entry["item_id"]))
            if existing and existing.get("status") == "resolved" and self._fingerprint(existing) == self._fingerprint(entry):
                continue
            active_candidates.append(candidate)
            compile_suggestion_entries.append(
                entry
            )
        queue.append_many(metadata_repair_entries)
        queue.upsert_compile_suggestions(compile_suggestion_entries)
        return active_candidates

    def _compile_suggestion_entry(self, candidate: dict) -> dict:
        return {
            "item_id": (
                f"compile_suggestion:{candidate['topic']}:{candidate['problem_cluster']}:"
                f"{candidate.get('sub_cluster_index', 1):04d}"
            ),
            "item_type": "compile_suggestion",
            "topic": candidate["topic"],
            "problem_cluster": candidate["problem_cluster"],
            "raw_count": candidate["raw_count"],
            "cluster_raw_count": candidate.get("cluster_raw_count", candidate["raw_count"]),
            "kind": candidate["kind"],
            "priority": candidate.get("priority", 1),
            "priority_label": candidate.get("priority_label", "P1"),
            "priority_reason": candidate.get("priority_reason", "general"),
            "sub_cluster_index": candidate.get("sub_cluster_index", 1),
            "sub_cluster_id": candidate.get("sub_cluster_id"),
            "raw_doc_ids": candidate.get("raw_doc_ids", []),
            "compile_priority_score": candidate.get("compile_priority_score", 0),
            "compile_strategy": candidate.get("compile_strategy", "Standard"),
            "deep_compile_rounds": candidate.get("deep_compile_rounds", 1),
            "prepare_params": {
                "topic": candidate["topic"],
                "problem_cluster": candidate["problem_cluster"],
                "doc_ids": candidate.get("raw_doc_ids", []),
                "sub_cluster_index": candidate.get("sub_cluster_index", 1),
            },
            "status": "open",
        }

    def _fingerprint(self, item: dict) -> tuple:
        return (
            tuple(str(doc_id) for doc_id in item.get("raw_doc_ids") or []),
            item.get("raw_count"),
            item.get("cluster_raw_count"),
            item.get("sub_cluster_index"),
            item.get("sub_cluster_id"),
        )

    def _candidate_sort_key(self, candidate: dict) -> tuple:
        kind = str(candidate.get("kind") or "")
        if kind == "undercompiled_cluster":
            kind_rank = 0
        elif kind == "ready_to_compile":
            kind_rank = 1
        else:
            kind_rank = 2

        return (
            kind_rank,
            int(candidate.get("priority", 1)),
            not candidate.get("purpose_aligned", False),
            int(candidate.get("sub_cluster_index", 1)),
            int(candidate.get("compiled_count", 0)),
            -int(candidate.get("compile_priority_score", 0)),
            -int(candidate.get("cluster_raw_count", candidate.get("raw_count", 0))),
            str(candidate.get("topic") or ""),
            str(candidate.get("problem_cluster") or ""),
            str(candidate.get("doc_id") or ""),
        )

    def _chunks(self, entries: list[dict], size: int) -> list[list[dict]]:
        return [entries[index:index + size] for index in range(0, len(entries), size)]

    def _sub_cluster_id(self, topic: str, problem_cluster: str, index: int) -> str:
        return f"{slugify_doc_id(topic)}_{slugify_doc_id(problem_cluster)}_{index:04d}"

    def _topic_matches_p0(self, topic: str, purpose: dict) -> bool:
        normalized_topic = slugify_doc_id(topic).replace("-", "")
        for purpose_topic in purpose.get("topics", []):
            normalized_purpose_topic = slugify_doc_id(str(purpose_topic)).replace("-", "")
            if normalized_topic == normalized_purpose_topic or normalized_topic in normalized_purpose_topic:
                return True
        return False

    def _query_signal_counts(self, wiki_root: Path, cluster_keys: set[tuple[str, str]]) -> defaultdict[tuple[str, str], dict[str, int]]:
        counts: defaultdict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"hits": 0, "misses": 0})
        path = wiki_root / "query_outcomes.jsonl"
        if not path.exists():
            return counts
        for entry in self._read_jsonl_lenient(path):
            query = str(entry.get("query") or "").lower()
            hit_count = int(entry.get("hit_count", 0) or 0)
            for topic, problem_cluster in cluster_keys:
                if topic.lower() not in query and problem_cluster.lower() not in query:
                    continue
                if hit_count > 0:
                    counts[(topic, problem_cluster)]["hits"] += 1
                else:
                    counts[(topic, problem_cluster)]["misses"] += 1
        return counts

    def _quality_failure_counts(self, wiki_root: Path) -> defaultdict[tuple[str, str], int]:
        counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        for entry in ReviewQueueRepository(wiki_root).read_all():
            if entry.get("item_type") != "compile_suggestion":
                continue
            if (entry.get("content_state") or {}).get("error_type") != "quality_rejected":
                continue
            topic = str(entry.get("topic") or "")
            problem_cluster = str(entry.get("problem_cluster") or "")
            if topic and problem_cluster:
                counts[(topic, problem_cluster)] += 1
        return counts

    def _eval_failure_counts(self, wiki_root: Path, manifest_entries: list[dict]) -> defaultdict[tuple[str, str], int]:
        counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        history_path = wiki_root / ".agent-wiki" / "eval_history.jsonl"
        history = self._read_jsonl_lenient(history_path)
        if not history:
            return counts

        manifest_by_doc_id = {
            str(entry.get("doc_id")): entry
            for entry in manifest_entries
            if entry.get("doc_id")
        }
        latest = history[-1]
        for query_row in latest.get("queries") or []:
            strict_recall = float(query_row.get("strict_recall_at_k", 0.0) or 0.0)
            loose_recall = float(query_row.get("loose_recall_at_k", 0.0) or 0.0)
            if strict_recall >= 1.0 and loose_recall >= 1.0:
                continue

            impacted_clusters: set[tuple[str, str]] = set()
            expected_doc_ids = list(query_row.get("expected_doc_ids") or [])
            acceptable_doc_ids = list(query_row.get("acceptable_doc_ids") or [])
            for doc_id in expected_doc_ids + acceptable_doc_ids:
                entry = manifest_by_doc_id.get(str(doc_id))
                if entry is None or entry.get("page_type") != "raw":
                    continue
                topic = str(entry.get("topic") or "")
                problem_cluster = str(entry.get("problem_cluster") or "")
                if topic and problem_cluster:
                    impacted_clusters.add((topic, problem_cluster))
            for cluster_key in impacted_clusters:
                counts[cluster_key] += 1
        return counts

    def _read_jsonl_lenient(self, path: Path) -> list[dict]:
        entries: list[dict] = []
        if not path.exists():
            return entries
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _cluster_staleness_days(self, entries: list[dict]) -> int:
        oldest: datetime | None = None
        for entry in entries:
            value = entry.get("updated_at") or entry.get("updated")
            if not value:
                continue
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            parsed = parsed.astimezone(UTC)
            if oldest is None or parsed < oldest:
                oldest = parsed
        if oldest is None:
            return 0
        return max((datetime.now(UTC) - oldest).days, 0)

    def _has_contradiction_markers(self, wiki_root: Path, entries: list[dict]) -> bool:
        markers = {"contradiction", "conflict", "dispute", "相互矛盾", "冲突"}
        for entry in entries:
            text = " ".join(str(entry.get(key) or "") for key in ("summary", "content", "doc_id")).lower()
            canonical_uri = entry.get("canonical_uri")
            if canonical_uri:
                page_path = wiki_root / str(canonical_uri)
                if page_path.exists():
                    text = f"{text} {page_path.read_text(encoding='utf-8').lower()}"
            if any(marker in text for marker in markers):
                return True
        return False

    def _compile_priority_score(
        self,
        *,
        raw_count: int,
        query_hit_frequency: int,
        query_miss_frequency: int,
        purpose_aligned: bool,
        existing_compiled_count: int,
        previous_quality_gate_failures: int,
        eval_failure_frequency: int,
        staleness_days: int,
        contradiction_markers_present: bool,
    ) -> int:
        score = 20
        score += min(raw_count, 10) * 4
        score += min(query_hit_frequency, 10) * 5
        score += min(query_miss_frequency, 10) * 6
        if purpose_aligned:
            score += 20
        score -= min(existing_compiled_count, 5) * 5
        score += min(previous_quality_gate_failures, 5) * 10
        score += min(eval_failure_frequency, 5) * 12
        score += min(staleness_days // 30, 4) * 5
        if contradiction_markers_present:
            score += 15
        return max(0, min(score, 100))

    def _compile_strategy(self, score: int) -> str:
        if score >= 80:
            return "Deep"
        if score < 45:
            return "Light"
        return "Standard"

    def _metadata_repair_candidates(self, manifest_entries: list[dict], pending: PendingStateRepository) -> list[dict]:
        candidates: list[dict] = []
        seen_doc_ids: set[str] = set()

        for entry in manifest_entries:
            if entry.get("page_type") != "raw":
                continue
            if entry.get("topic") and entry.get("problem_cluster") and entry.get("summary"):
                continue
            doc_id = entry.get("doc_id")
            if not doc_id or doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            candidates.append({
                "kind": "needs_metadata_repair",
                "doc_id": doc_id,
                "topic": entry.get("topic") or "",
                "problem_cluster": entry.get("problem_cluster") or "",
                "reason": "manifest raw page missing retrieval metadata",
                "purpose_aligned": False,
            })

        if pending.pending_manifest_path.exists():
            for line in pending.pending_manifest_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                import json
                entry = json.loads(line)
                if entry.get("page_type") != "raw":
                    continue
                doc_id = entry.get("doc_id")
                if not doc_id or doc_id in seen_doc_ids:
                    continue
                seen_doc_ids.add(doc_id)
                candidates.append({
                    "kind": "needs_metadata_repair",
                    "doc_id": doc_id,
                    "topic": entry.get("topic") or "",
                    "problem_cluster": entry.get("problem_cluster") or "",
                    "reason": "pending raw page requires metadata repair",
                    "purpose_aligned": False,
                })

        return candidates
