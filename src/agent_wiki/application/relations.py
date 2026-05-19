import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class RelationsService:
    def detect_co_occurrences(self, wiki: WikiConfig, threshold: int = 2) -> list[dict]:
        wiki_root = Path(wiki.workspace_path)
        outcomes_path = wiki_root / "query_outcomes.jsonl"
        if not outcomes_path.exists():
            return []

        hits_path = wiki_root / "query_hits.jsonl"
        if not hits_path.exists():
            return []

        doc_buckets = self._doc_buckets(wiki_root)
        query_hits: dict[str, list[str]] = {}
        for line in hits_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            query_id = entry["query_id"]
            query_hits.setdefault(query_id, []).append(entry["doc_id"])

        pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        for doc_ids in query_hits.values():
            bucketed_doc_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
            for doc_id in doc_ids:
                bucket = doc_buckets.get(doc_id)
                if bucket is None:
                    if doc_buckets:
                        continue
                    bucket = ("", "")
                bucketed_doc_ids[bucket].add(doc_id)
            for bucket_doc_ids in bucketed_doc_ids.values():
                for a, b in combinations(sorted(bucket_doc_ids), 2):
                    pair_counts[(a, b)] += 1

        candidates = []
        for (a, b), count in pair_counts.items():
            if count >= threshold:
                candidates.append({
                    "doc_ids": [a, b],
                    "co_occurrence_count": count,
                })

        candidates.sort(key=lambda c: c["co_occurrence_count"], reverse=True)
        return candidates

    def detect_cross_references(self, wiki: WikiConfig) -> list[dict]:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        entries = manifest.read_all()
        doc_buckets = self._doc_buckets_from_entries(entries)

        ref_to_bucket_docs: dict[tuple[str, tuple[str, str]], set[str]] = defaultdict(set)
        for entry in entries:
            if entry.get("page_type") == "raw":
                continue
            doc_id = str(entry["doc_id"])
            bucket = doc_buckets.get(doc_id)
            if bucket is None:
                continue
            for ref in entry.get("source_refs", []):
                ref_to_bucket_docs[(str(ref), bucket)].add(doc_id)

        pair_to_refs: dict[tuple[str, str], list[str]] = defaultdict(list)
        for (ref, _bucket), doc_ids in ref_to_bucket_docs.items():
            if len(doc_ids) < 2:
                continue
            for a, b in combinations(sorted(doc_ids), 2):
                pair_to_refs[(a, b)].append(ref)

        candidates = []
        for (a, b), shared_refs in pair_to_refs.items():
            candidates.append({
                "doc_ids": [a, b],
                "shared_refs": sorted(shared_refs),
            })

        candidates.sort(key=lambda c: len(c["shared_refs"]), reverse=True)
        return candidates

    def _doc_buckets(self, wiki_root: Path) -> dict[str, tuple[str, str]]:
        return self._doc_buckets_from_entries(ManifestRepository(wiki_root).read_all())

    def _doc_buckets_from_entries(self, entries: list[dict]) -> dict[str, tuple[str, str]]:
        buckets: dict[str, tuple[str, str]] = {}
        for entry in entries:
            doc_id = entry.get("doc_id")
            if not doc_id:
                continue
            buckets[str(doc_id)] = (
                str(entry.get("topic") or ""),
                str(entry.get("problem_cluster") or ""),
            )
        return buckets

    def detect_and_enqueue_co_occurrences(
        self,
        wiki: WikiConfig,
        threshold: int = 2,
        max_new_candidates: int = 20,
    ) -> list[dict]:
        candidates = self.detect_co_occurrences(wiki, threshold)
        if not candidates:
            return candidates
        wiki_root = Path(wiki.workspace_path)
        queue = ReviewQueueRepository(wiki_root)
        existing_pairs = self._existing_co_occurrence_pairs(queue.read_all())
        new_entries: list[dict] = []
        new_candidates: list[dict] = []
        for candidate in candidates:
            pair = tuple(sorted(candidate["doc_ids"]))
            if pair in existing_pairs:
                continue
            existing_pairs.add(pair)
            new_candidates.append(candidate)
            new_entries.append({
                "item_id": self._co_occurrence_signal_item_id(pair),
                "item_type": "signal_candidate",
                "relation_type": "co_occurrence",
                "doc_ids": list(pair),
                "co_occurrence_count": candidate["co_occurrence_count"],
                "status": "open",
            })
            if len(new_entries) >= max_new_candidates:
                break
        queue.append_many(new_entries)
        return new_candidates

    def detect_and_enqueue_cross_references(self, wiki: WikiConfig) -> list[dict]:
        candidates = self.detect_cross_references(wiki)
        if not candidates:
            return candidates
        wiki_root = Path(wiki.workspace_path)
        queue = ReviewQueueRepository(wiki_root)
        for candidate in candidates:
            queue.append({
                "item_id": f"signal_candidate:cross_reference:{candidate['doc_ids'][0]}:{candidate['doc_ids'][1]}",
                "item_type": "signal_candidate",
                "relation_type": "cross_reference",
                "doc_ids": candidate["doc_ids"],
                "shared_refs": candidate["shared_refs"],
                "status": "open",
            })
        return candidates

    def _co_occurrence_signal_item_id(self, doc_ids: tuple[str, str]) -> str:
        return f"signal_candidate:co_occurrence:{doc_ids[0]}:{doc_ids[1]}"

    def _existing_co_occurrence_pairs(self, items: list[dict]) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for item in items:
            if item.get("item_type") != "signal_candidate":
                continue
            if item.get("relation_type") != "co_occurrence":
                continue
            doc_ids = item.get("doc_ids")
            if isinstance(doc_ids, list) and len(doc_ids) == 2:
                pair = tuple(sorted(str(doc_id) for doc_id in doc_ids))
                pairs.add(pair)
                continue
            item_id = str(item.get("item_id") or "")
            prefix = "signal_candidate:co_occurrence:"
            if not item_id.startswith(prefix):
                continue
            _, _, a, b = item_id.split(":", 3)
            pairs.add(tuple(sorted((a, b))))
        return pairs
