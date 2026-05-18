from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.infrastructure.retrieval.tokenizer import tokenize
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


@dataclass(frozen=True)
class RelationTypeDefinition:
    name: str
    patterns: tuple[str, ...]
    subject_type: str
    object_type: str
    symmetric: bool = False


class RelationSchemaRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.schema_path = wiki_root / "relation_schema.yaml"

    def load(self) -> list[RelationTypeDefinition]:
        if not self.schema_path.exists():
            return []
        data = yaml.safe_load(self.schema_path.read_text(encoding="utf-8")) or {}
        definitions: list[RelationTypeDefinition] = []
        for item in data.get("relation_types", []):
            name = str(item.get("name") or "").strip()
            patterns = tuple(str(pattern) for pattern in item.get("patterns", []) if str(pattern).strip())
            if not name or not patterns:
                continue
            definitions.append(
                RelationTypeDefinition(
                    name=name,
                    patterns=patterns,
                    subject_type=str(item.get("subject_type") or "entity"),
                    object_type=str(item.get("object_type") or "entity"),
                    symmetric=bool(item.get("symmetric", False)),
                )
            )
        return definitions


class RelationExtractor:
    _SUBJECT_GROUPS = ("subject", "person", "investor", "a", "tech")
    _OBJECT_GROUPS = ("object", "org", "company", "b", "target")

    def __init__(self, definitions: list[RelationTypeDefinition]) -> None:
        self.definitions = definitions

    def extract(self, *, text: str, source_doc_id: str, extracted_at: str | None = None) -> list[dict]:
        timestamp = extracted_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        relations: list[dict] = []
        seen: set[tuple[str, str, str, str]] = set()
        for definition in self.definitions:
            for pattern in definition.patterns:
                compiled = re.compile(pattern, flags=re.IGNORECASE | re.MULTILINE)
                for match in compiled.finditer(text):
                    subject = self._clean_entity(self._first_group(match, self._SUBJECT_GROUPS))
                    object_ = self._clean_entity(self._first_group(match, self._OBJECT_GROUPS))
                    if not subject or not object_:
                        continue
                    self._append_relation(relations, seen, definition, subject, object_, source_doc_id, timestamp)
                    if definition.symmetric:
                        self._append_relation(relations, seen, definition, object_, subject, source_doc_id, timestamp)
        return relations

    def _append_relation(
        self,
        relations: list[dict],
        seen: set[tuple[str, str, str, str]],
        definition: RelationTypeDefinition,
        subject: str,
        object_: str,
        source_doc_id: str,
        extracted_at: str,
    ) -> None:
        key = (subject, definition.name, object_, source_doc_id)
        if key in seen:
            return
        seen.add(key)
        relations.append(
            {
                "subject": subject,
                "relation": definition.name,
                "object": object_,
                "subject_type": definition.subject_type,
                "object_type": definition.object_type,
                "source_doc_id": source_doc_id,
                "confidence": 1.0,
                "extracted_at": extracted_at,
            }
        )

    def _first_group(self, match: re.Match[str], names: tuple[str, ...]) -> str | None:
        groups = match.groupdict()
        for name in names:
            value = groups.get(name)
            if value:
                return value
        return None

    def _clean_entity(self, value: str | None) -> str:
        if value is None:
            return ""
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned.strip(" #\t\r\n.,;:!?，。；：！？[]()（）\"\'")


class KnowledgeGraphRepository:
    def __init__(self, wiki_root: Path, wiki_id: str) -> None:
        self.wiki_root = wiki_root
        self.wiki_id = wiki_id
        self.path = wiki_root / "knowledge_graph.jsonl"

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        entries: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def replace_all(self, entries: list[dict]) -> None:
        if not entries:
            self.path.unlink(missing_ok=True)
            return
        with self.path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def rebuild_from_raw_pages(self) -> int:
        definitions = RelationSchemaRepository(self.wiki_root).load()
        if not definitions:
            self.path.unlink(missing_ok=True)
            return 0
        manifest = ManifestRepository(self.wiki_root)
        extractor = RelationExtractor(definitions)
        relations: list[dict] = []
        extracted_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        for entry in manifest.read_all():
            if entry.get("page_type") != "raw":
                continue
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                continue
            page_path = self.wiki_root / str(canonical_uri)
            if not page_path.exists() or not page_path.is_file():
                continue
            relations.extend(
                extractor.extract(
                    text=page_path.read_text(encoding="utf-8"),
                    source_doc_id=str(entry.get("doc_id")),
                    extracted_at=extracted_at,
                )
            )
        self.replace_all(relations)
        return len(relations)


class KnowledgeGraphRetrievalProvider:
    def __init__(self, wiki_root: Path, wiki_id: str) -> None:
        self.repository = KnowledgeGraphRepository(wiki_root, wiki_id=wiki_id)
        self.wiki_id = wiki_id

    def search(self, query: str, top_k: int = 10) -> list[RetrievalHit]:
        terms = set(tokenize(query))
        if not terms:
            return []
        hits_by_doc: dict[str, RetrievalHit] = {}
        for relation in self.repository.read_all():
            score = self._score_relation(relation, terms)
            if score <= 0:
                continue
            doc_id = str(relation.get("source_doc_id") or "")
            if not doc_id:
                continue
            metadata = {
                "graph_score": score,
                "graph_subject": relation.get("subject"),
                "graph_relation": relation.get("relation"),
                "graph_object": relation.get("object"),
            }
            existing = hits_by_doc.get(doc_id)
            if existing is None or score > existing.score:
                hits_by_doc[doc_id] = RetrievalHit(
                    wiki_id=self.wiki_id,
                    doc_id=doc_id,
                    score=score,
                    section="knowledge_graph",
                    metadata=metadata,
                )
        hits = list(hits_by_doc.values())
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def _score_relation(self, relation: dict[str, Any], query_terms: set[str]) -> float:
        fields = [relation.get("subject"), relation.get("relation"), relation.get("object")]
        relation_terms: set[str] = set()
        for field in fields:
            relation_terms.update(tokenize(str(field or "").replace("_", " ")))
        overlap = query_terms & relation_terms
        if not overlap:
            return 0.0
        return float(len(overlap)) * 5.0
