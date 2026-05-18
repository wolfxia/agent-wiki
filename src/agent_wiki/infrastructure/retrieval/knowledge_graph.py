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
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


CONFIDENCE_EXTRACTED = "EXTRACTED"
CONFIDENCE_INFERRED = "INFERRED"
CONFIDENCE_AMBIGUOUS = "AMBIGUOUS"
_VALID_CONFIDENCE_LABELS = {CONFIDENCE_EXTRACTED, CONFIDENCE_INFERRED, CONFIDENCE_AMBIGUOUS}
_DEFAULT_CONFIDENCE_SCORES = {
    CONFIDENCE_EXTRACTED: 1.0,
    CONFIDENCE_INFERRED: 0.7,
    CONFIDENCE_AMBIGUOUS: 0.4,
}
_QUERY_CONFIDENCE_WEIGHTS = {
    CONFIDENCE_EXTRACTED: 1.0,
    CONFIDENCE_INFERRED: 0.7,
}


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

    def extract(
        self,
        *,
        text: str,
        source_doc_id: str,
        extracted_at: str | None = None,
        wiki_id: str | None = None,
    ) -> list[dict]:
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
                    evidence = self._clean_evidence(match.group(0))
                    self._append_relation(relations, seen, definition, subject, object_, source_doc_id, timestamp, evidence, wiki_id)
                    if definition.symmetric:
                        self._append_relation(relations, seen, definition, object_, subject, source_doc_id, timestamp, evidence, wiki_id)
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
        evidence: str,
        wiki_id: str | None,
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
                "confidence_label": CONFIDENCE_EXTRACTED,
                "confidence_score": _DEFAULT_CONFIDENCE_SCORES[CONFIDENCE_EXTRACTED],
                "evidence": evidence,
                "source_refs": [f"{wiki_id}:{source_doc_id}"] if wiki_id else [source_doc_id],
                "extracted_at": extracted_at,
            }
        )

    def _clean_evidence(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

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
        original = re.sub(r"\s+", " ", value).strip()
        if self._has_markdown_boundary_noise(original):
            return ""

        cleaned = self._remove_inline_markdown(original)
        cleaned = cleaned.strip(" #\t\r\n.,;:!?，。；：！？[]()（）\"\'")
        if not self._is_meaningful_entity(cleaned):
            return ""
        return cleaned

    def _has_markdown_boundary_noise(self, value: str) -> bool:
        if "|" in value:
            return True
        return bool(re.match(r"^(?:[-*+]\s+|\d+\.\s+|#+\s+|>\s*)", value))

    def _remove_inline_markdown(self, value: str) -> str:
        cleaned = value
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"\[\[([^\]]+)\]\]", r"\1", cleaned)
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _is_meaningful_entity(self, value: str) -> bool:
        if len(value) < 2:
            return False
        if "|" in value:
            return False
        if re.match(r"^(?:[-*+]\s+|\d+\.\s+|#+\s+|>\s*)", value):
            return False
        if re.search(r"(?:^|\s)-$", value):
            return False
        if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", value):
            return False
        return True


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

    def backfill_confidence_labels(self) -> int:
        entries = self.read_all()
        changed = 0
        normalized_entries: list[dict] = []
        for entry in entries:
            entry_changed = False
            normalized = dict(entry)
            label = self._normalize_confidence_label(normalized.get("confidence_label"))
            if normalized.get("confidence_label") != label:
                normalized["confidence_label"] = label
                entry_changed = True
            score = normalized.get("confidence_score")
            if not isinstance(score, int | float):
                normalized["confidence_score"] = _DEFAULT_CONFIDENCE_SCORES[label]
                entry_changed = True
            if not normalized.get("source_refs") and normalized.get("source_doc_id"):
                normalized["source_refs"] = [f"{self.wiki_id}:{normalized['source_doc_id']}"]
                entry_changed = True
            normalized.setdefault("evidence", "")
            normalized_entries.append(normalized)
            if entry_changed:
                changed += 1
        if changed:
            self.replace_all(normalized_entries)
        return changed

    def enqueue_ambiguous_reviews(self, queue: ReviewQueueRepository) -> int:
        created = 0
        for relation in self.read_all():
            if self._normalize_confidence_label(relation.get("confidence_label")) != CONFIDENCE_AMBIGUOUS:
                continue
            item_id = relation_review_item_id(relation)
            if queue.find(item_id) is not None:
                continue
            queue.append(
                {
                    "item_id": item_id,
                    "item_type": "relation_review",
                    "status": "open",
                    "content_state": {
                        "subject": relation.get("subject"),
                        "object": relation.get("object"),
                        "source": relation.get("subject"),
                        "target": relation.get("object"),
                        "relation": relation.get("relation"),
                        "relation_type": relation.get("relation"),
                        "confidence_label": CONFIDENCE_AMBIGUOUS,
                        "confidence_score": relation.get("confidence_score"),
                        "evidence": relation.get("evidence"),
                        "source_refs": relation.get("source_refs") or [],
                    },
                }
            )
            created += 1
        return created

    def update_relation_confidence(self, item_id: str, confidence_label: str) -> bool:
        label = self._normalize_confidence_label(confidence_label)
        entries = self.read_all()
        updated = False
        for index, relation in enumerate(entries):
            if relation_review_item_id(relation) != item_id:
                continue
            entries[index] = {
                **relation,
                "confidence_label": label,
                "confidence_score": _DEFAULT_CONFIDENCE_SCORES[label],
            }
            updated = True
            break
        if updated:
            self.replace_all(entries)
        return updated

    def remove_relation(self, item_id: str) -> bool:
        entries = self.read_all()
        remaining = [relation for relation in entries if relation_review_item_id(relation) != item_id]
        if len(remaining) == len(entries):
            return False
        self.replace_all(remaining)
        return True

    def _normalize_confidence_label(self, value: object) -> str:
        label = str(value or CONFIDENCE_INFERRED).upper()
        if label not in _VALID_CONFIDENCE_LABELS:
            return CONFIDENCE_INFERRED
        return label

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
                    wiki_id=self.wiki_id,
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
                "graph_confidence_label": self._confidence_label(relation),
                "graph_confidence_score": self._confidence_score(relation),
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
        label = self._confidence_label(relation)
        if label == CONFIDENCE_AMBIGUOUS:
            return 0.0
        fields = [relation.get("subject"), relation.get("relation"), relation.get("object")]
        relation_terms: set[str] = set()
        for field in fields:
            relation_terms.update(tokenize(str(field or "").replace("_", " ")))
        overlap = query_terms & relation_terms
        if not overlap:
            return 0.0
        return float(len(overlap)) * 5.0 * _QUERY_CONFIDENCE_WEIGHTS.get(label, 0.7)

    def _confidence_label(self, relation: dict[str, Any]) -> str:
        label = str(relation.get("confidence_label") or CONFIDENCE_INFERRED).upper()
        if label not in _VALID_CONFIDENCE_LABELS:
            return CONFIDENCE_INFERRED
        return label

    def _confidence_score(self, relation: dict[str, Any]) -> float:
        value = relation.get("confidence_score")
        if isinstance(value, int | float):
            return float(value)
        return _DEFAULT_CONFIDENCE_SCORES[self._confidence_label(relation)]


def relation_review_item_id(relation: dict[str, Any]) -> str:
    return f"relation_review:{relation.get('subject')}:{relation.get('object')}:{relation.get('relation')}"
