from collections import defaultdict
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

        for (topic, problem_cluster), raw_entries in raw_cluster_entries.items():
            raw_entries.sort(key=lambda entry: str(entry.get("doc_id") or ""))
            count = len(raw_entries)
            if count < threshold:
                continue
            compiled_count = compiled_cluster_counts.get((topic, problem_cluster), 0)
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
                    "purpose_aligned": purpose_reader.is_aligned(topic),
                    "priority": 0 if self._topic_matches_p0(topic, purpose) else 1,
                    "priority_label": "P0" if self._topic_matches_p0(topic, purpose) else "P1",
                    "priority_reason": "purpose_aligned" if self._topic_matches_p0(topic, purpose) else "general",
                })

        candidates.sort(
            key=lambda c: (
                c["kind"] == "needs_metadata_repair",
                not c.get("purpose_aligned", False),
                -c.get("raw_count", 0),
                c.get("doc_id", ""),
            )
        )
        return candidates

    def detect_and_enqueue(self, wiki: WikiConfig, threshold: int = RAW_ACCUMULATION_THRESHOLD) -> list[dict]:
        candidates = self.detect(wiki, threshold)
        if not candidates:
            return candidates

        wiki_root = Path(wiki.workspace_path)
        queue = ReviewQueueRepository(wiki_root)
        queue.remove_old_format_compile_suggestions()
        for candidate in candidates:
            if candidate["kind"] == "needs_metadata_repair":
                queue.append({
                    "item_id": f"metadata_repair:{candidate['doc_id']}",
                    "item_type": "metadata_repair",
                    "doc_id": candidate["doc_id"],
                    "reason": candidate.get("reason", "missing metadata"),
                    "status": "open",
                })
                continue

            queue.append({
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
                "prepare_params": {
                    "topic": candidate["topic"],
                    "problem_cluster": candidate["problem_cluster"],
                    "doc_ids": candidate.get("raw_doc_ids", []),
                    "sub_cluster_index": candidate.get("sub_cluster_index", 1),
                },
                "status": "open",
            })
        return candidates

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
