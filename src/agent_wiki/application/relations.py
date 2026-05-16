import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
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

        query_hits: dict[int, list[str]] = {}
        for line in hits_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            query_idx = entry["query_idx"]
            query_hits.setdefault(query_idx, []).append(entry["doc_id"])

        pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        for doc_ids in query_hits.values():
            unique = sorted(set(doc_ids))
            for a, b in combinations(unique, 2):
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

        ref_to_docs: dict[str, list[str]] = defaultdict(list)
        for entry in entries:
            if entry.get("page_type") == "raw":
                continue
            for ref in entry.get("source_refs", []):
                ref_to_docs[ref].append(entry["doc_id"])

        candidates = []
        seen: set[tuple[str, ...]] = set()
        for ref, doc_ids in ref_to_docs.items():
            if len(doc_ids) < 2:
                continue
            for a, b in combinations(sorted(doc_ids), 2):
                key = (a, b)
                if key in seen:
                    continue
                seen.add(key)
                shared = [r for r, docs in ref_to_docs.items() if a in docs and b in docs]
                candidates.append({
                    "doc_ids": [a, b],
                    "shared_refs": shared,
                })

        candidates.sort(key=lambda c: len(c["shared_refs"]), reverse=True)
        return candidates
