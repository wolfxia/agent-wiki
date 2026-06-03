from pathlib import Path

from pydantic import BaseModel, Field

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.enums import PageType
from agent_wiki.extensions.page_types import get_page_type_registry
from agent_wiki.infrastructure.retrieval.knowledge_graph import KnowledgeGraphRepository, RelationSchemaError, RelationSchemaRepository
from agent_wiki.infrastructure.retrieval.index_consistency import IndexConsistencyChecker
from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class LintResult(BaseModel):
    ok: bool
    issues: list[str]
    metrics: dict = Field(default_factory=dict)


class LintService:
    def run(self, wiki: WikiConfig) -> LintResult:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        issues: list[str] = []

        try:
            RelationSchemaRepository(wiki_root).load()
        except RelationSchemaError as error:
            issues.append(f"relation_schema invalid: {error}")

        for entry in manifest.read_all():
            if entry.get("page_type") == PageType.RAW.value:
                if not entry.get("topic") or not entry.get("problem_cluster") or not entry.get("summary"):
                    issues.append(f"missing raw metadata for {entry.get('doc_id', 'unknown')}")
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                issues.append(f"missing canonical_uri for {entry.get('doc_id', 'unknown')}")
                continue
            page_path = wiki_root / canonical_uri
            if not page_path.exists():
                issues.append(f"missing page for {entry.get('doc_id')}")
            page_type = entry.get("page_type")
            if page_type and get_page_type_registry().get(str(page_type)).requires_source_refs and not entry.get("source_refs"):
                issues.append(f"missing source_refs for compiled page {entry.get('doc_id')}")

        pending_state = PendingStateRepository(wiki_root)
        pending_entries = pending_state.read_pending_manifest()
        pending_doc_ids = {entry.get("doc_id") for entry in pending_entries if entry.get("doc_id")}

        index_issues = IndexConsistencyChecker().check(wiki_root)
        for issue in index_issues:
            if issue.startswith("retrieval index entry without manifest entry:"):
                doc_id = issue.rsplit(":", 1)[1].strip()
                if doc_id in pending_doc_ids:
                    continue
            issues.append(issue)

        for marker in pending_state.read_stale_markers():
            issues.append(f"stale marker for {marker.get('doc_id', 'unknown')}: {marker.get('reason', '')}")

        return LintResult(
            ok=not issues,
            issues=issues,
            metrics={
                "kg_coverage": self._kg_coverage_metrics(manifest.read_all(), wiki_root),
            },
        )

    def _kg_coverage_metrics(self, manifest_entries: list[dict], wiki_root: Path) -> dict[str, float | int | list[str]]:
        raw_doc_ids = {
            str(entry.get("doc_id"))
            for entry in manifest_entries
            if entry.get("page_type") == PageType.RAW.value and entry.get("doc_id")
        }
        relation_doc_ids = {
            str(entry.get("source_doc_id"))
            for entry in KnowledgeGraphRepository(wiki_root, wiki_id="lint").read_all()
            if entry.get("source_doc_id")
        }
        covered = raw_doc_ids & relation_doc_ids
        raw_total = len(raw_doc_ids)
        raw_with_relations = len(covered)
        raw_without_relations = raw_total - raw_with_relations
        raw_without_relation_doc_ids = sorted(raw_doc_ids - relation_doc_ids)
        coverage = round(raw_with_relations / raw_total, 3) if raw_total else 0.0
        return {
            "raw_total": raw_total,
            "raw_with_relations": raw_with_relations,
            "raw_without_relations": raw_without_relations,
            "raw_without_relation_doc_ids": raw_without_relation_doc_ids,
            "coverage": coverage,
        }
