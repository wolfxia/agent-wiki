from __future__ import annotations
from pathlib import Path
import re

from pydantic import BaseModel

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.doc_id import normalize_doc_id, slugify_doc_id
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class CompilePrepareInput(BaseModel):
    topic: str
    problem_cluster: str
    doc_ids: list[str] | None = None
    max_items: int = 8
    sub_cluster_index: int = 1


class CompilePrepareItem(BaseModel):
    doc_id: str
    title: str | None = None
    summary: str | None = None
    source_ref: str
    canonical_uri: str | None = None
    claims: list[str]
    content_preview: str


class CompilePrepareResult(BaseModel):
    topic: str
    problem_cluster: str
    sub_cluster_id: str
    proposed_page_type: str
    proposed_doc_id: str
    agent_objective: str
    total_raw_count: int
    source_refs: list[str]
    existing_atom_summaries: list[dict]
    relationship_hints: list[dict]
    contradiction_markers: list[dict]
    items: list[CompilePrepareItem]


_TOTAL_PREVIEW_BUDGET = 6000


class CompilePrepareService:
    def prepare(self, wiki: WikiConfig, actor: ResolvedActor, data: CompilePrepareInput) -> CompilePrepareResult:
        decision = PermissionService().check(actor, "query", wiki, "raw")
        if not decision.allowed:
            raise PermissionError(decision.reason)

        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        raw_entries = [
            entry
            for entry in manifest.read_all()
            if entry.get("page_type") == "raw"
            and entry.get("topic") == data.topic
            and entry.get("problem_cluster") == data.problem_cluster
        ]
        raw_entries.sort(key=lambda entry: str(entry.get("doc_id") or ""))
        total_raw_count = len(raw_entries)
        if data.doc_ids:
            by_id = {str(entry.get("doc_id")): entry for entry in raw_entries}
            raw_entries = [by_id[doc_id] for doc_id in data.doc_ids if doc_id in by_id]
        else:
            raw_entries = raw_entries[: max(data.max_items, 0)]

        item_count = max(len(raw_entries), 1)
        items = [self._prepare_item(wiki, wiki_root, entry, total_items=item_count) for entry in raw_entries]
        sub_cluster_id = self._sub_cluster_id(data.topic, data.problem_cluster, data.sub_cluster_index)
        return CompilePrepareResult(
            topic=data.topic,
            problem_cluster=data.problem_cluster,
            sub_cluster_id=sub_cluster_id,
            proposed_page_type="atom",
            proposed_doc_id=f"atom-{normalize_doc_id(data.topic)}-{normalize_doc_id(data.problem_cluster)}-{data.sub_cluster_index:04d}",
            agent_objective="create_retrieval_ready_atom",
            total_raw_count=total_raw_count,
            source_refs=[item.source_ref for item in items],
            existing_atom_summaries=self._existing_atom_summaries(manifest, data.topic, data.problem_cluster),
            relationship_hints=self._relationship_hints(items),
            contradiction_markers=self._contradiction_markers(items),
            items=items,
        )

    def _prepare_item(self, wiki: WikiConfig, wiki_root: Path, entry: dict, *, total_items: int) -> CompilePrepareItem:
        canonical_uri = entry.get("canonical_uri")
        content = ""
        if canonical_uri:
            page_path = wiki_root / str(canonical_uri)
            if page_path.exists() and page_path.is_file():
                content = page_path.read_text(encoding="utf-8")
        doc_id = str(entry.get("doc_id") or "")
        max_preview_chars = self._preview_budget_chars(total_items=total_items)
        return CompilePrepareItem(
            doc_id=doc_id,
            title=entry.get("title"),
            summary=entry.get("summary"),
            source_ref=f"{wiki.wiki_id}:{doc_id}",
            canonical_uri=str(canonical_uri) if canonical_uri else None,
            claims=self._extract_claims(content),
            content_preview=content[:max_preview_chars],
        )

    def _extract_claims(self, content: str) -> list[str]:
        cleaned_lines = [line for line in content.splitlines() if not line.strip().startswith("#")]
        cleaned = "\n".join(cleaned_lines)
        explicit_claims: list[str] = []
        for line in cleaned.splitlines():
            stripped = line.strip().lstrip("-* ").strip()
            if stripped.lower().startswith("claim"):
                first_sentence = stripped.split(". ", maxsplit=1)[0].rstrip(".") + "."
                explicit_claims.append(first_sentence)
        if explicit_claims:
            return explicit_claims[:8]

        claims: list[str] = []
        sentences = re.split(r"(?<=[.!?])\s+", cleaned.replace("\n", " "))
        for sentence in sentences:
            stripped = sentence.strip().lstrip("-*").strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if (
                any(char.isdigit() for char in stripped)
                or re.search(r"\b[A-Z][a-z]+\b", stripped)
                or "metric" in lowered
                or "evidence" in lowered
                or "camera pipeline" in lowered
            ):
                claims.append(stripped if stripped.endswith((".", "!", "?")) else stripped + ".")
            if len(claims) >= 8:
                break
        return claims

    def _existing_atom_summaries(self, manifest: ManifestRepository, topic: str, problem_cluster: str) -> list[dict]:
        summaries: list[dict] = []
        for entry in manifest.read_all():
            if entry.get("page_type") != "atom":
                continue
            if entry.get("topic") != topic:
                continue
            if entry.get("problem_cluster") != problem_cluster:
                continue
            summary = entry.get("summary")
            if not summary:
                continue
            summaries.append(
                {
                    "doc_id": str(entry.get("doc_id") or ""),
                    "summary": str(summary),
                    "problem_cluster": str(entry.get("problem_cluster") or ""),
                }
            )
        return summaries[:10]

    def _preview_budget_chars(self, total_items: int) -> int:
        item_count = max(total_items, 1)
        return max(1200, min(3000, _TOTAL_PREVIEW_BUDGET // item_count))

    def _relationship_hints(self, items: list[CompilePrepareItem]) -> list[dict]:
        hints: list[dict] = []
        for index, item in enumerate(items):
            for other in items[index + 1:]:
                hints.append({
                    "doc_ids": [item.doc_id, other.doc_id],
                    "relationship": "same_topic_cluster",
                })
        return hints

    def _contradiction_markers(self, items: list[CompilePrepareItem]) -> list[dict]:
        markers: list[dict] = []
        for item in items:
            text = item.content_preview.lower()
            if "contradict" not in text and "conflict" not in text:
                continue
            markers.append({"doc_id": item.doc_id, "text": item.content_preview})
        return markers

    def _sub_cluster_id(self, topic: str, problem_cluster: str, index: int) -> str:
        return f"{slugify_doc_id(topic)}_{slugify_doc_id(problem_cluster)}_{index:04d}"
