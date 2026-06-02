from __future__ import annotations
import json
import re
from pathlib import Path

from agent_wiki.infrastructure.runtime.claim_annotations import ClaimAnnotationRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class ClaimAnnotationService:
    def annotate_incremental(self, wiki_root: Path, limit: int = 50) -> dict:
        effective_limit = max(int(limit), 0)
        repository = ClaimAnnotationRepository(wiki_root)
        state = self._read_state(wiki_root)
        processed: dict[str, dict] = dict(state.get("processed") or {})
        annotated_count = 0

        for entry in ManifestRepository(wiki_root).read_all():
            if annotated_count >= effective_limit:
                break
            if entry.get("page_type") != "atom":
                continue
            doc_id = str(entry.get("doc_id") or "")
            if not doc_id:
                continue
            page_path = self._page_path(wiki_root, entry, doc_id)
            if page_path is None:
                continue
            fingerprint = self._fingerprint(page_path)
            if processed.get(doc_id) == fingerprint:
                continue
            repository.upsert(
                {
                    "doc_id": doc_id,
                    "claims": self._claims_from_page(page_path, entry),
                    "annotation_method": "rule",
                }
            )
            processed[doc_id] = fingerprint
            annotated_count += 1

        self._write_state(wiki_root, {"processed": processed})
        return {"annotated_count": annotated_count, "limit": effective_limit}

    def _page_path(self, wiki_root: Path, entry: dict, doc_id: str) -> Path | None:
        canonical_uri = entry.get("canonical_uri")
        path = wiki_root / str(canonical_uri) if canonical_uri else wiki_root / "pages" / f"{doc_id}.md"
        return path if path.exists() and path.is_file() else None

    def _fingerprint(self, path: Path) -> dict:
        stat = path.stat()
        return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}

    def _claims_from_page(self, page_path: Path, manifest_entry: dict) -> list[dict]:
        text = page_path.read_text(encoding="utf-8")
        claims = []
        for claim_text in self._extract_claim_lines(text):
            label, rationale = self._classify_claim(claim_text, manifest_entry)
            claims.append(
                {
                    "text": claim_text,
                    "confidence_label": label,
                    "evidence_refs": self._evidence_refs_for_claim(claim_text, manifest_entry, label),
                    "rationale": rationale,
                }
            )
        return claims

    def _extract_claim_lines(self, content: str) -> list[str]:
        lines = content.splitlines()
        in_claims = False
        claims: list[str] = []
        for line in lines:
            stripped = line.strip()
            if re.match(r"^##\s+Claims\s*$", stripped, flags=re.IGNORECASE):
                in_claims = True
                continue
            if in_claims and stripped.startswith("## "):
                break
            if not in_claims:
                continue
            claim = re.sub(r"^[-*]\s+", "", stripped).strip()
            if claim:
                claims.append(claim)
        return claims

    def _classify_claim(self, claim_text: str, manifest_entry: dict) -> tuple[str, str]:
        lowered = claim_text.lower()
        if re.search(r"\b(conflict|conflicting|contradict|contradictory|ambiguous|uncertain)\b", lowered) or re.search(r"冲突|矛盾|不确定|含糊|模糊", claim_text):
            return "AMBIGUOUS", "ambiguous or conflicting wording present"
        if self._has_explicit_evidence_marker(claim_text, manifest_entry):
            return "EXTRACTED", "explicit evidence marker present"
        if re.search(r"\d", claim_text):
            return "INFERRED", "numeric claim without explicit citation"
        return "INFERRED", "no explicit evidence marker found"

    def _has_explicit_evidence_marker(self, claim_text: str, manifest_entry: dict) -> bool:
        lowered = claim_text.lower()
        if re.search(r"\bdoi\s*:", lowered) or "http://" in lowered or "https://" in lowered:
            return True
        for ref in manifest_entry.get("source_refs") or []:
            ref_text = str(ref)
            if ref_text and (ref_text in claim_text or ref_text.split(":")[-1] in claim_text):
                return True
        return False

    def _evidence_refs_for_claim(self, claim_text: str, manifest_entry: dict, label: str) -> list[str]:
        if label != "EXTRACTED":
            return []
        refs = []
        for ref in manifest_entry.get("source_refs") or []:
            ref_text = str(ref)
            if ref_text and (ref_text in claim_text or ref_text.split(":")[-1] in claim_text):
                refs.append(ref_text)
        return refs

    def _state_path(self, wiki_root: Path) -> Path:
        return wiki_root / ".agent-wiki" / "claim_annotation_state.json"

    def _read_state(self, wiki_root: Path) -> dict:
        path = self._state_path(wiki_root)
        if not path.exists():
            return {"processed": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"processed": {}}
        return payload if isinstance(payload, dict) else {"processed": {}}

    def _write_state(self, wiki_root: Path, state: dict) -> None:
        path = self._state_path(wiki_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
