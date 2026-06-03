import json
from pathlib import Path

from agent_wiki.application.claim_annotations import ClaimAnnotationService
from agent_wiki.infrastructure.runtime.claim_annotations import ClaimAnnotationRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


def test_claim_annotation_repository_round_trips_by_doc_id(temp_wiki_root: Path) -> None:
    repository = ClaimAnnotationRepository(temp_wiki_root)

    repository.upsert(
        {
            "doc_id": "atom-claims-1",
            "claims": [
                {
                    "text": "Mobile-GS reaches 116FPS.",
                    "confidence_label": "EXTRACTED",
                    "evidence_refs": ["personal-1:raw-paper-1"],
                    "rationale": "paper citation present",
                }
            ],
            "annotation_method": "compile",
        }
    )

    stored = repository.find("atom-claims-1")

    assert stored["doc_id"] == "atom-claims-1"
    assert stored["claims"][0]["confidence_label"] == "EXTRACTED"
    assert stored["annotated_at"]


def test_claim_annotation_repository_skips_malformed_jsonl_lines(temp_wiki_root: Path) -> None:
    path = temp_wiki_root / ".agent-wiki" / "claim_annotations.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "not-json\n"
        + json.dumps({"doc_id": "atom-valid", "claims": []}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    entries = ClaimAnnotationRepository(temp_wiki_root).read_all()

    assert [entry["doc_id"] for entry in entries] == ["atom-valid"]


def test_claim_annotation_service_classifies_claim_confidence_rules(temp_wiki_root: Path) -> None:
    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "atom-rule-claims.md").write_text(
        "# Atom\n\n"
        "## Claims\n"
        "- Mobile-GS reaches 116FPS according to doi:10.1145/test and raw-paper-1.\n"
        "- LLM inference market grows 40% in 2026.\n"
        "- The evidence is conflicting and ambiguous for this claim.\n\n"
        "## Evidence\n- raw-paper-1\n",
        encoding="utf-8",
    )
    ManifestRepository(temp_wiki_root).upsert(
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-rule-claims",
            "page_type": "atom",
            "canonical_uri": "pages/atom-rule-claims.md",
            "source_refs": ["personal-1:raw-paper-1"],
        }
    )

    result = ClaimAnnotationService().annotate_incremental(temp_wiki_root, limit=10)
    stored = ClaimAnnotationRepository(temp_wiki_root).find("atom-rule-claims")

    assert result["annotated_count"] == 1
    assert [claim["confidence_label"] for claim in stored["claims"]] == ["EXTRACTED", "INFERRED", "AMBIGUOUS"]
    assert stored["annotation_method"] == "rule"


def test_claim_annotation_service_incremental_backfill_only_processes_changed_pages(temp_wiki_root: Path) -> None:
    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    for index in range(2):
        doc_id = f"atom-incremental-{index}"
        (pages / f"{doc_id}.md").write_text(f"# Atom {index}\n\n## Claims\n- Claim {index}.\n", encoding="utf-8")
        ManifestRepository(temp_wiki_root).upsert(
            {
                "wiki_id": "personal-1",
                "doc_id": doc_id,
                "page_type": "atom",
                "canonical_uri": f"pages/{doc_id}.md",
            }
        )

    first = ClaimAnnotationService().annotate_incremental(temp_wiki_root, limit=1)
    second = ClaimAnnotationService().annotate_incremental(temp_wiki_root, limit=10)
    third = ClaimAnnotationService().annotate_incremental(temp_wiki_root, limit=10)

    assert first["annotated_count"] == 1
    assert second["annotated_count"] == 1
    assert third["annotated_count"] == 0
