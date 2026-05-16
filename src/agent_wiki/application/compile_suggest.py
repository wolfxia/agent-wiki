from collections import defaultdict
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository

RAW_ACCUMULATION_THRESHOLD = 3


class CompileSuggestService:
    def detect(self, wiki: WikiConfig, threshold: int = RAW_ACCUMULATION_THRESHOLD) -> list[dict]:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        entries = manifest.read_all()

        cluster_counts: dict[tuple[str, str], int] = defaultdict(int)
        for entry in entries:
            if entry.get("page_type") == "raw":
                key = (entry.get("topic", ""), entry.get("problem_cluster", ""))
                cluster_counts[key] += 1

        candidates = []
        for (topic, problem_cluster), count in cluster_counts.items():
            if count >= threshold:
                candidates.append({
                    "topic": topic,
                    "problem_cluster": problem_cluster,
                    "raw_count": count,
                })

        candidates.sort(key=lambda c: c["raw_count"], reverse=True)
        return candidates
