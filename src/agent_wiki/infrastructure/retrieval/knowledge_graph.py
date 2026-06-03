from __future__ import annotations

import json
import re
from dataclasses import dataclass
from agent_wiki._compat import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.extensions.page_types import get_page_type_registry, normalize_page_type
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

# P1-5: Relation type weights for retrieval scoring.
# Higher weight = more semantically precise relation (less noise).
_RELATION_WEIGHTS: dict[str, float] = {
    "founded": 1.5,
    "powers": 1.5,
    "product_integrates": 2.0,
    "depends_on": 1.0,
    "competes_with": 1.0,
    "works_at": 1.0,
    "invested_in": 1.0,
}
_DEFAULT_RELATION_WEIGHT = 1.0
_QUERY_CONFIDENCE_WEIGHTS = {
    CONFIDENCE_EXTRACTED: 1.0,
    CONFIDENCE_INFERRED: 0.7,
}


class RelationSchemaError(ValueError):
    pass


@dataclass(frozen=True)
class RelationTypeDefinition:
    name: str
    patterns: tuple[str, ...]
    pattern_confidence_labels: tuple[str, ...] = ()
    subject_type: str = "entity"
    object_type: str = "entity"
    symmetric: bool = False


class RelationSchemaRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.schema_path = wiki_root / "relation_schema.yaml"

    def load(self) -> list[RelationTypeDefinition]:
        if not self.schema_path.exists():
            return []
        data = yaml.safe_load(self.schema_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise RelationSchemaError("relation_schema.yaml must contain a top-level mapping")
        definitions: list[RelationTypeDefinition] = []
        for item in data.get("relation_types", []):
            name = str(item.get("name") or "").strip()
            raw_patterns = item.get("patterns", [])
            patterns: list[str] = []
            confidence_labels: list[str] = []
            for entry in raw_patterns:
                # P0-2c: support both string patterns and {pattern, confidence_label} objects
                if isinstance(entry, dict):
                    pattern_str = str(entry.get("pattern") or "").strip()
                    label = str(entry.get("confidence_label") or CONFIDENCE_EXTRACTED).strip().upper()
                    if pattern_str:
                        patterns.append(pattern_str)
                        confidence_labels.append(label)
                elif isinstance(entry, str) and entry.strip():
                    patterns.append(entry.strip())
                    confidence_labels.append(CONFIDENCE_EXTRACTED)
            if not name or not patterns:
                continue
            definitions.append(
                RelationTypeDefinition(
                    name=name,
                    patterns=tuple(patterns),
                    pattern_confidence_labels=tuple(confidence_labels),
                    subject_type=str(item.get("subject_type") or "entity"),
                    object_type=str(item.get("object_type") or "entity"),
                    symmetric=bool(item.get("symmetric", False)),
                )
            )
        for definition in definitions:
            self._validate_definition(definition)
        return definitions

    def _validate_definition(self, definition: RelationTypeDefinition) -> None:
        if len(definition.pattern_confidence_labels) != len(definition.patterns):
            raise RelationSchemaError(
                f"relation_schema entry '{definition.name}' has mismatched patterns and confidence labels"
            )
        subject_groups = set(RelationExtractor._SUBJECT_GROUPS)
        object_groups = set(RelationExtractor._OBJECT_GROUPS)
        for index, pattern in enumerate(definition.patterns, start=1):
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise RelationSchemaError(
                    f"relation_schema pattern {definition.name}[{index}] failed to compile: {exc}"
                ) from exc
            group_names = set(compiled.groupindex)
            if not group_names & subject_groups:
                raise RelationSchemaError(
                    f"relation_schema pattern {definition.name}[{index}] is missing a subject named group"
                )
            if not group_names & object_groups:
                raise RelationSchemaError(
                    f"relation_schema pattern {definition.name}[{index}] is missing an object named group"
                )
            label = definition.pattern_confidence_labels[index - 1]
            if label not in _VALID_CONFIDENCE_LABELS:
                raise RelationSchemaError(
                    f"relation_schema pattern {definition.name}[{index}] has invalid confidence label: {label}"
                )


class RelationExtractor:
    _SUBJECT_GROUPS = ("subject", "person", "investor", "a", "tech")
    _OBJECT_GROUPS = ("object", "org", "company", "b", "target")

    def __init__(self, definitions: list[RelationTypeDefinition]) -> None:
        self.definitions = definitions

    def _compile_pattern(self, pattern: str) -> re.Pattern[str]:
        flags = re.MULTILINE
        # Keep ASCII-capitalization constraints meaningful for strict English patterns.
        if not re.search(r"\[A-Z][^\]]*\[A-Za-z", pattern):
            flags |= re.IGNORECASE
        return re.compile(pattern, flags=flags)

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
            for idx, pattern in enumerate(definition.patterns):
                # P0-2c: use per-pattern confidence label if available
                confidence_label = (
                    definition.pattern_confidence_labels[idx]
                    if idx < len(definition.pattern_confidence_labels)
                    else CONFIDENCE_EXTRACTED
                )
                compiled = self._compile_pattern(pattern)
                for match in compiled.finditer(text):
                    subject = self._clean_entity(self._first_group(match, self._SUBJECT_GROUPS))
                    object_ = self._clean_entity(self._first_group(match, self._OBJECT_GROUPS))
                    if not subject or not object_:
                        continue
                    evidence = self._clean_evidence(match.group(0))
                    self._append_relation(relations, seen, definition, subject, object_, source_doc_id, timestamp, evidence, wiki_id, confidence_label)
                    if definition.symmetric:
                        self._append_relation(relations, seen, definition, object_, subject, source_doc_id, timestamp, evidence, wiki_id, confidence_label)
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
        confidence_label: str = CONFIDENCE_EXTRACTED,
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
                "confidence": _DEFAULT_CONFIDENCE_SCORES.get(confidence_label, 1.0),
                "confidence_label": confidence_label,
                "confidence_score": _DEFAULT_CONFIDENCE_SCORES.get(confidence_label, 1.0),
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
        # P0-2b: truncate overlong entities to 30 chars
        if len(cleaned) > 30:
            cleaned = cleaned[:30].rstrip(" #\t\r\n.,;:!?，。；：！？[]()（）\"\'")
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
        # P0-2b: reject entities ending with trailing function words
        _TRAILING_STOP_RE = re.compile(r"(?:\u7684|\u5728|\u4e86|\u7740|\u8fc7|\u662f|\u6709|with|from|by|at|of|for|in|on|the|a|an|and|or|but)$")
        if _TRAILING_STOP_RE.search(value):
            return False
        # P0-2b: reject entities dominated by digits (>50% digit chars)
        digit_count = sum(1 for c in value if c.isdigit())
        if digit_count > len(value) * 0.5:
            return False
        return True


class KnowledgeGraphRepository:
    def __init__(self, wiki_root: Path, wiki_id: str) -> None:
        self.wiki_root = wiki_root
        self.wiki_id = wiki_id
        self.path = wiki_root / "knowledge_graph.jsonl"
        self.state_path = wiki_root / ".agent-wiki" / "knowledge_graph_state.json"

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
        schema_repository = RelationSchemaRepository(self.wiki_root)
        definitions = schema_repository.load()
        if not definitions:
            self.path.unlink(missing_ok=True)
            self.state_path.unlink(missing_ok=True)
            return 0
        manifest = ManifestRepository(self.wiki_root)
        extractor = RelationExtractor(definitions)
        existing_relations = self.read_all()
        state = self._read_state()
        schema_fingerprint = self._path_fingerprint(schema_repository.schema_path)
        doc_state = state.get("docs") if state.get("schema") == schema_fingerprint and isinstance(state.get("docs"), dict) else {}
        relations_by_doc: dict[str, list[dict]] = {}
        for relation in existing_relations:
            source_doc_id = str(relation.get("source_doc_id") or "")
            if not source_doc_id:
                continue
            relations_by_doc.setdefault(source_doc_id, []).append(relation)

        extracted_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        next_doc_state: dict[str, dict] = {}
        for entry in manifest.read_all():
            if entry.get("page_type") != "raw":
                continue
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                continue
            page_path = self.wiki_root / str(canonical_uri)
            if not page_path.exists() or not page_path.is_file():
                continue
            doc_id = str(entry.get("doc_id"))
            fingerprint = self._page_fingerprint(page_path)
            next_doc_state[doc_id] = fingerprint
            if doc_state.get(doc_id) == fingerprint:
                continue
            relations_by_doc[doc_id] = extractor.extract(
                text=page_path.read_text(encoding="utf-8"),
                source_doc_id=doc_id,
                extracted_at=extracted_at,
                wiki_id=self.wiki_id,
            )

        removed_doc_ids = set(relations_by_doc) - set(next_doc_state)
        for doc_id in removed_doc_ids:
            relations_by_doc.pop(doc_id, None)

        relations: list[dict] = []
        for doc_id in sorted(relations_by_doc):
            relations.extend(relations_by_doc[doc_id])
        self.replace_all(relations)
        self._write_state({"schema": schema_fingerprint, "docs": next_doc_state})
        return len(relations)

    def _read_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    def _page_fingerprint(self, page_path: Path) -> dict:
        return self._path_fingerprint(page_path)

    def _path_fingerprint(self, path: Path) -> dict:
        stat = path.stat()
        return {
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
        }


class KnowledgeGraphRetrievalProvider:
    def __init__(self, wiki_root: Path, wiki_id: str) -> None:
        self.repository = KnowledgeGraphRepository(wiki_root, wiki_id=wiki_id)
        self.wiki_id = wiki_id

    def _page_type_from_doc_id(self, doc_id: str) -> str:
        normalized = doc_id.lower().replace("_", "-")
        for prefix in sorted(get_page_type_registry().names(), key=len, reverse=True):
            if normalized.startswith(prefix + "-"):
                return prefix
        return ""

    def _allowed_page_types(self, filters: dict | None) -> set[str] | None:
        if not filters:
            return None
        raw_page_types = filters.get("page_types")
        if raw_page_types:
            return {normalize_page_type(page_type) for page_type in raw_page_types if str(page_type).strip()}
        raw_page_type = filters.get("page_type")
        if raw_page_type:
            return {normalize_page_type(raw_page_type)}
        return None

    def search(self, query: str, top_k: int = 10, filters: dict | None = None) -> list[RetrievalHit]:
        terms = set(tokenize(query))
        if not terms:
            return []
        allowed_page_types = self._allowed_page_types(filters)
        hits_by_doc: dict[str, RetrievalHit] = {}
        for relation in self.repository.read_all():
            score = self._score_relation(relation, terms)
            if score <= 0:
                continue
            doc_id = str(relation.get("source_doc_id") or "")
            if not doc_id:
                continue
            if allowed_page_types is not None:
                inferred_type = self._page_type_from_doc_id(doc_id)
                if inferred_type not in allowed_page_types:
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
        relation_name = str(relation.get("relation") or "")
        relation_weight = _RELATION_WEIGHTS.get(relation_name, _DEFAULT_RELATION_WEIGHT)
        fields = [relation.get("subject"), relation.get("relation"), relation.get("object")]
        relation_terms: set[str] = set()
        for field in fields:
            relation_terms.update(tokenize(str(field or "").replace("_", " ")))
        overlap = query_terms & relation_terms
        if not overlap:
            return 0.0
        return float(len(overlap)) * 5.0 * _QUERY_CONFIDENCE_WEIGHTS.get(label, 0.7) * relation_weight

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
