import json
from pathlib import Path

from pydantic import BaseModel

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.enums import PageType
from agent_wiki.infrastructure.retrieval.index_consistency import IndexConsistencyChecker
from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class LintResult(BaseModel):
    ok: bool
    issues: list[str]


class LintService:
    def run(self, wiki: WikiConfig) -> LintResult:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        issues: list[str] = []

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
            if page_type in {PageType.ATOM.value, PageType.SYNTHESIS.value, PageType.PRINCIPLE.value} and not entry.get("source_refs"):
                issues.append(f"missing source_refs for compiled page {entry.get('doc_id')}")

        pending_state = PendingStateRepository(wiki_root)
        pending_entries: list[dict] = []
        if pending_state.pending_manifest_path.exists():
            pending_entries = [
                json.loads(line)
                for line in pending_state.pending_manifest_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
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

        return LintResult(ok=not issues, issues=issues)
