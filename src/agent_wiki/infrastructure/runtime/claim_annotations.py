from __future__ import annotations
import json
import logging
import os
from agent_wiki._compat import UTC
from datetime import datetime
from pathlib import Path
import tempfile

from agent_wiki.infrastructure.runtime.file_lock import FileLock


logger = logging.getLogger(__name__)


class ClaimAnnotationRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.wiki_root = wiki_root
        self.path = wiki_root / ".agent-wiki" / "claim_annotations.jsonl"
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def upsert(self, entry: dict) -> None:
        normalized = self._normalize(entry)
        with self._exclusive_lock():
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
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                logger.warning("Skipping corrupt claim annotation line %s in %s: %s", line_number, self.path, error)
                continue
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
        fd, temp_path = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temp = Path(temp_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for entry in entries:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            self._fsync_parent_dir()
        except Exception:
            temp.unlink(missing_ok=True)
            raise

    def _exclusive_lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(self.lock_path)

    def _fsync_parent_dir(self) -> None:
        try:
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
