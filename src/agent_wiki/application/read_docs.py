from __future__ import annotations

from pathlib import Path
import re

from pydantic import BaseModel, Field

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


_FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", re.DOTALL)


class WikiDocResult(BaseModel):
    wiki_id: str
    doc_id: str
    page_type: str | None = None
    canonical_uri: str
    metadata: dict = Field(default_factory=dict)
    content: str


class InboundRefResult(BaseModel):
    wiki_id: str
    doc_id: str
    ref_count: int
    refs: list[dict] = Field(default_factory=list)


class WikiReadService:
    def get_doc(self, wiki: WikiConfig, actor: ResolvedActor, doc_id: str) -> WikiDocResult:
        manifest = ManifestRepository(Path(wiki.workspace_path))
        entry = manifest.find(doc_id)
        if entry is None:
            raise ValueError(f"unknown doc_id: {doc_id}")
        self._check_read_permission(wiki, actor, entry)

        canonical_uri = str(entry.get("canonical_uri") or "")
        if not canonical_uri:
            raise ValueError(f"doc_id has no canonical_uri: {doc_id}")
        page_path = Path(wiki.workspace_path) / canonical_uri
        if not page_path.exists() or not page_path.is_file():
            raise ValueError(f"doc page is missing: {doc_id}")

        content = self._strip_yaml_frontmatter(page_path.read_text(encoding="utf-8"))
        return WikiDocResult(
            wiki_id=str(entry.get("wiki_id") or wiki.wiki_id),
            doc_id=doc_id,
            page_type=entry.get("page_type"),
            canonical_uri=canonical_uri,
            metadata=dict(entry),
            content=content,
        )

    def inbound_refs(self, wiki: WikiConfig, actor: ResolvedActor, doc_id: str) -> InboundRefResult:
        manifest = ManifestRepository(Path(wiki.workspace_path))
        target = manifest.find(doc_id)
        if target is None:
            raise ValueError(f"unknown doc_id: {doc_id}")
        self._check_read_permission(wiki, actor, target)

        target_ref = f"{wiki.wiki_id}:{doc_id}"
        refs: list[dict] = []
        for entry in manifest.read_all():
            if entry.get("doc_id") == doc_id:
                continue
            if not self._can_read_entry(wiki, actor, entry):
                continue

            fields: list[str] = []
            if target_ref in self._string_list(entry.get("source_refs")):
                fields.append("source_refs")
            if doc_id in {self._normalize_wikilink(link) for link in self._string_list(entry.get("wikilinks"))}:
                fields.append("wikilinks")
            if not fields:
                continue

            refs.append(
                {
                    "wiki_id": str(entry.get("wiki_id") or wiki.wiki_id),
                    "doc_id": entry.get("doc_id"),
                    "page_type": entry.get("page_type"),
                    "canonical_uri": entry.get("canonical_uri"),
                    "fields": fields,
                    "metadata": dict(entry),
                }
            )

        return InboundRefResult(wiki_id=wiki.wiki_id, doc_id=doc_id, ref_count=len(refs), refs=refs)

    def _check_read_permission(self, wiki: WikiConfig, actor: ResolvedActor, entry: dict) -> None:
        if not self._can_read_entry(wiki, actor, entry):
            raise PermissionError("no read permission for document")

    def _can_read_entry(self, wiki: WikiConfig, actor: ResolvedActor, entry: dict) -> bool:
        page_type = str(entry.get("page_type") or "raw")
        return PermissionService().check(actor, "query", wiki, page_type).allowed

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    def _normalize_wikilink(self, value: str) -> str:
        link = value.strip()
        if link.startswith("[[") and link.endswith("]]"):
            link = link[2:-2]
        link = link.split("|", maxsplit=1)[0].split("#", maxsplit=1)[0].strip()
        if ":" in link:
            _, link = link.split(":", maxsplit=1)
        return link

    def _strip_yaml_frontmatter(self, content: str) -> str:
        previous = None
        stripped = content
        while previous != stripped:
            previous = stripped
            stripped = _FRONTMATTER_PATTERN.sub("", stripped, count=1)
        return stripped
