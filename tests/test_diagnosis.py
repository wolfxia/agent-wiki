import json
from agent_wiki._compat import UTC
from datetime import datetime, timedelta
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.diagnosis import DiagnosisService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def _wiki(temp_wiki_root: Path):
    return RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={
            "workspace_path": str(temp_wiki_root),
            "tuning_defaults": {
                "query_ranking": {
                    "atom_page_type_boost": 4.0,
                    "synthesis_page_type_boost": 4.0,
                    "principle_page_type_boost": 2.0,
                    "purpose_boost": 3.25,
                    "topic_alignment_boost": 6.5,
                    "topic_seed_score": 8.0,
                    "rerank_candidate_multiplier": 3,
                }
            },
        }
    )


def _write_eval_history(temp_wiki_root: Path, entries: list[dict]) -> None:
    runtime_root = temp_wiki_root / ".agent-wiki"
    runtime_root.mkdir(exist_ok=True)
    (runtime_root / "eval_history.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )


def test_diagnosis_detects_parameter_drift_against_frozen_baseline(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    runtime_root = temp_wiki_root / ".agent-wiki"
    runtime_root.mkdir(exist_ok=True)
    (runtime_root / "runtime_tuning.json").write_text(
        json.dumps({"query_ranking": {"purpose_boost": 9.0}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (runtime_root / "frozen_baseline.json").write_text(
        json.dumps({"query_ranking": {"purpose_boost": 3.25}}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = DiagnosisService().analyze(wiki)

    diagnosis = next(item for item in report["diagnoses"] if item["diagnosis_type"] == "parameter_drift")
    assert diagnosis["recommendation"]["parameter_name"] == "query_ranking.purpose_boost"
    assert diagnosis["recommendation"]["target_value"] == 3.25


def test_diagnosis_detects_retrieval_ranking_shift_from_eval_drop(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_eval_history(
        temp_wiki_root,
        [
            {
                "timestamp": "2026-05-18T00:00:00Z",
                "eval_file": "eval/retrieval_queries.jsonl",
                "k": 5,
                "runtime_tuning": {"query_ranking": {"purpose_boost": 3.25}},
                "metrics": {
                    "strict_recall_at_k": 0.81,
                    "loose_recall_at_k": 0.88,
                    "must_not_violation_at_k": 0.0,
                    "mrr": 0.6,
                    "compiled_hit_ratio": 0.9,
                },
                "queries": [],
            },
            {
                "timestamp": "2026-05-19T00:00:00Z",
                "eval_file": "eval/retrieval_queries.jsonl",
                "k": 5,
                "runtime_tuning": {"query_ranking": {"purpose_boost": 3.25}},
                "metrics": {
                    "strict_recall_at_k": 0.69,
                    "loose_recall_at_k": 0.77,
                    "must_not_violation_at_k": 0.0,
                    "mrr": 0.48,
                    "compiled_hit_ratio": 0.89,
                },
                "queries": [],
            },
        ],
    )

    report = DiagnosisService().analyze(wiki)

    diagnosis = next(item for item in report["diagnoses"] if item["diagnosis_type"] == "retrieval_ranking_shift")
    assert diagnosis["recommendation"]["parameter_name"] == "query_ranking.topic_alignment_boost"
    assert diagnosis["recommendation"]["direction"] == "increase"


def test_diagnosis_detects_compile_quality_degradation(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-diagnosis-1",
            topic="diagnosis",
            problem_cluster="compile-quality",
            content="# Raw diagnosis",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-diagnosis-1",
            page_type="atom",
            topic="diagnosis",
            problem_cluster="compile-quality",
            content="# Atom diagnosis\n\nNo structured evidence.",
            source_refs=["personal-1:raw-diagnosis-1"],
        ),
    )
    (temp_wiki_root / "review_queue.jsonl").write_text(
        json.dumps(
            {
                "item_id": "compile_suggestion:quality-1",
                "item_type": "compile_suggestion",
                "status": "failed",
                "content_state": {"error_type": "quality_rejected"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = DiagnosisService().analyze(wiki)

    diagnosis = next(item for item in report["diagnoses"] if item["diagnosis_type"] == "compile_quality_degradation")
    assert diagnosis["recommendation"]["action"] == "tighten_compile_prompt_or_repair"
    assert diagnosis["evidence"]["compile_failure_breakdown"]["quality_rejected"] == 1


def test_diagnosis_detects_coverage_gap_from_zero_hit_queries(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    (temp_wiki_root / "query_outcomes.jsonl").write_text(
        "".join(
            json.dumps({"query_id": f"q-{index}", "query": "knowledge gap", "hit_count": 0}, ensure_ascii=False) + "\n"
            for index in range(3)
        ),
        encoding="utf-8",
    )

    report = DiagnosisService().analyze(wiki)

    diagnosis = next(item for item in report["diagnoses"] if item["diagnosis_type"] == "coverage_gap")
    assert diagnosis["recommendation"]["action"] == "expand_compile_coverage"
    assert diagnosis["evidence"]["zero_hit_queries"]["knowledge gap"] == 3


def test_diagnosis_detects_staleness_for_hot_old_compiled_page(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-stale-1",
            topic="staleness",
            problem_cluster="hot-cluster",
            content="# Raw stale",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-stale-1",
            page_type="atom",
            topic="staleness",
            problem_cluster="hot-cluster",
            summary="Stale hot atom.",
            aliases=["stale"],
            confidence="high",
            wikilinks=["[[raw-stale-1]]"],
            content="# Atom stale\n\n## Claims\n- Claim.\n\n## Evidence\n- Evidence.",
            source_refs=["personal-1:raw-stale-1"],
        ),
    )
    manifest_path = temp_wiki_root / "MANIFEST.jsonl"
    entries = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stale_ts = (datetime.now(UTC) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    for entry in entries:
        if entry.get("doc_id") == "atom-stale-1":
            entry["updated_at"] = stale_ts
    manifest_path.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries), encoding="utf-8")
    (temp_wiki_root / "query_outcomes.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "query_id": f"stale-q-{index}",
                    "query": "stale hot",
                    "hit_count": 1,
                    "accepted_doc_ids": ["atom-stale-1"],
                    "rejected_doc_ids": [],
                },
                ensure_ascii=False,
            )
            + "\n"
            for index in range(3)
        ),
        encoding="utf-8",
    )

    report = DiagnosisService().analyze(wiki)

    diagnosis = next(item for item in report["diagnoses"] if item["diagnosis_type"] == "staleness")
    assert diagnosis["recommendation"]["action"] == "refresh_hot_cluster"
    assert diagnosis["recommendation"]["doc_ids"] == ["atom-stale-1"]
