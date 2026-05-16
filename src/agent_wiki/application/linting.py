import json
from pathlib import Path

from pydantic import BaseModel

from agent_wiki.bootstrap.registry_loader import WikiConfig
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
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                issues.append(f"missing canonical_uri for {entry.get('doc_id', 'unknown')}")
                continue
            page_path = wiki_root / canonical_uri
            if not page_path.exists():
                issues.append(f"missing page for {entry.get('doc_id')}")

        retrieval_index_path = wiki_root / "retrieval_index.jsonl"
        if retrieval_index_path.exists():
            for line in retrieval_index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                card = json.loads(line)
                if manifest.find(card["doc_id"]) is None:
                    issues.append(f"retrieval index entry without manifest entry: {card['doc_id']}")

        return LintResult(ok=not issues, issues=issues)
