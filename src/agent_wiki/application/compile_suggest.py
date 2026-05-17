from collections import defaultdict
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository
from agent_wiki.infrastructure.storage.purpose_reader import PurposeReader

RAW_ACCUMULATION_THRESHOLD = 3


class CompileSuggestService:
    def detect(self, wiki: WikiConfig, threshold: int = RAW_ACCUMULATION_THRESHOLD) -> list[dict]:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        pending = PendingStateRepository(wiki_root)
        purpose_reader = PurposeReader(wiki_root)
        entries = manifest.read_all()

        candidates: list[dict] = []
        candidates.extend(self._metadata_repair_candidates(entries, pending))

        raw_cluster_counts: dict[tuple[str, str], int] = defaultdict(int)
        compiled_cluster_counts: dict[tuple[str, str], int] = defaultdict(int)
        for entry in entries:
            page_type = entry.get("page_type")
            topic = entry.get("topic") or ""
            problem_cluster = entry.get("problem_cluster") or ""
            if page_type == "raw":
                if topic and problem_cluster:
                    raw_cluster_counts[(topic, problem_cluster)] += 1
                continue
            if topic and problem_cluster:
                compiled_cluster_counts[(topic, problem_cluster)] += 1

        for (topic, problem_cluster), count in raw_cluster_counts.items():
            if count < threshold:
                continue
            compiled_count = compiled_cluster_counts.get((topic, problem_cluster), 0)
            candidates.append({
                "kind": "undercompiled_cluster" if compiled_count == 0 else "ready_to_compile",
                "topic": topic,
                "problem_cluster": problem_cluster,
                "raw_count": count,
                "compiled_count": compiled_count,
                "purpose_aligned": purpose_reader.is_aligned(topic),
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
                "item_id": f"compile_suggestion:{candidate['topic']}:{candidate['problem_cluster']}",
                "item_type": "compile_suggestion",
                "topic": candidate["topic"],
                "problem_cluster": candidate["problem_cluster"],
                "raw_count": candidate["raw_count"],
                "kind": candidate["kind"],
                "status": "open",
            })
        return candidates

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
