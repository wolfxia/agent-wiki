import json
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository

_COMPILED_PAGE_TYPES = {"atom", "synthesis", "principle"}


class QualityReportService:
    def generate(self, wiki: WikiConfig) -> dict:
        wiki_root = Path(wiki.workspace_path)

        query_count, hit_rate = self._query_metrics(wiki_root)
        manifest = ManifestRepository(wiki_root)
        entries = manifest.read_all()
        raw_count, compiled_count = self._page_counts(entries)
        compile_rate = (compiled_count / raw_count) if raw_count else 0.0
        orphan_count = self._orphan_count(entries)

        return {
            "query_count": query_count,
            "hit_rate": hit_rate,
            "raw_count": raw_count,
            "compiled_count": compiled_count,
            "compile_rate": compile_rate,
            "orphan_count": orphan_count,
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
