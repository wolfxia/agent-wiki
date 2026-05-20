import json
from datetime import UTC, datetime
from pathlib import Path


class ClaimAnnotationRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.wiki_root = wiki_root
        self.path = wiki_root / ".agent-wiki" / "claim_annotations.jsonl"

    def upsert(self, entry: dict) -> None:
        normalized = self._normalize(entry)
        entries = self.read_all()
        replaced = False
        for index, existing in enumerate(entries):
            if existing.get("doc_id") == normalized.get("doc_id"):
                entries[index] = {**existing, **normalized}
                replaced = True
                break
        if not replaced:
            entries.append(normalized)
        self._write_all(entries)

    def find(self, doc_id: str) -> dict | None:
        for entry in self.read_all():
            if entry.get("doc_id") == doc_id:
                return entry
        return None

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        entries: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                entries.append(payload)
        return entries

    def _normalize(self, entry: dict) -> dict:
        doc_id = str(entry.get("doc_id") or "").strip()
        if not doc_id:
            raise ValueError("claim annotation doc_id is required")
        normalized = dict(entry)
        normalized["doc_id"] = doc_id
        normalized["claims"] = [self._normalize_claim(claim) for claim in normalized.get("claims") or []]
        normalized.setdefault("annotation_method", "rule")
        normalized.setdefault("annotated_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        return normalized

    def _normalize_claim(self, claim: dict) -> dict:
        normalized = dict(claim)
        normalized["text"] = str(normalized.get("text") or "").strip()
        normalized["confidence_label"] = self._normalize_confidence(normalized.get("confidence_label"))
        normalized["evidence_refs"] = [str(ref) for ref in normalized.get("evidence_refs") or []]
        normalized.setdefault("rationale", "")
        return normalized

    def _normalize_confidence(self, value: object) -> str:
        label = str(value or "INFERRED").upper()
        return label if label in {"EXTRACTED", "INFERRED", "AMBIGUOUS"} else "INFERRED"

    def _write_all(self, entries: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
