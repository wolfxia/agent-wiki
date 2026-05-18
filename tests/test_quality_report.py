from pathlib import Path
import json

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.application.quality_report import QualityReportService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_quality_report_returns_zeros_for_empty_wiki(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )

    report = QualityReportService().generate(wiki)

    assert report["query_count"] == 0
    assert report["hit_rate"] == 0.0
    assert report["raw_count"] == 0
    assert report["compiled_count"] == 0
    assert report["compile_rate"] == 0.0
    assert report["orphan_count"] == 0
    assert report["compile_failure_rate"] == 0.0
    assert report["compile_failure_breakdown"] == {}
    assert report["avg_compile_latency_seconds"] == 0.0
    assert report["metadata_completeness"] == 0.0
    assert report["cluster_coverage"] == 0.0
    assert report["mature_cluster_coverage"] == 0.0
    assert report["relation_stats"] == {
        "total": 0,
        "extracted": 0,
        "inferred": 0,
        "ambiguous": 0,
        "pending_review": 0,
    }


def test_quality_report_computes_hit_rate(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-qr-1", topic="testing", problem_cluster="cluster-qr",
            content="# Raw qr", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-qr-1", page_type="atom", topic="testing",
            problem_cluster="cluster-qr",
            content="# Atom qr\n\nQuality report metric.",
            source_refs=["personal-1:raw-qr-1"],
        ),
    )

    # 2 hits, 1 miss → hit_rate = 2/3
    query_service.execute(wiki=wiki, actor=actor, data=QueryInput(query="quality report metric"))
    query_service.execute(wiki=wiki, actor=actor, data=QueryInput(query="quality report"))
    query_service.execute(wiki=wiki, actor=actor, data=QueryInput(query="zzz-no-match"))

    report = QualityReportService().generate(wiki)

    assert report["query_count"] == 3
    assert abs(report["hit_rate"] - (2 / 3)) < 0.01


def test_quality_report_computes_compile_rate(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # 4 raw, 2 compiled (atom+synthesis) → compile_rate = 2/4 = 0.5
    for i in range(4):
        capture_service.execute(
            wiki=wiki, actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-cr-{i}", topic="testing",
                problem_cluster=f"cluster-cr-{i}",
                content=f"# Raw cr {i}", source_refs=[],
            ),
        )

    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-cr-1", page_type="atom", topic="testing",
            problem_cluster="cluster-cr-0",
            content="# Atom cr 1", source_refs=["personal-1:raw-cr-0"],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="synth-cr-1", page_type="synthesis", topic="testing",
            problem_cluster="cluster-cr-1",
            content="# Synth cr 1", source_refs=["personal-1:raw-cr-1"],
        ),
    )

    report = QualityReportService().generate(wiki)

    assert report["raw_count"] == 4
    assert report["compiled_count"] == 2
    assert report["compile_rate"] == 0.5


def test_quality_report_counts_orphans(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # raw-orphan-1 referenced by atom-ref-1 → not orphan
    # raw-orphan-2 referenced by no one → orphan
    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-orphan-1", topic="testing",
            problem_cluster="cluster-orphan",
            content="# Raw orphan 1", source_refs=[],
        ),
    )
    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-orphan-2", topic="testing",
            problem_cluster="cluster-orphan-2",
            content="# Raw orphan 2", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-ref-1", page_type="atom", topic="testing",
            problem_cluster="cluster-orphan",
            content="# Atom ref", source_refs=["personal-1:raw-orphan-1"],
        ),
    )

    report = QualityReportService().generate(wiki)

    assert report["orphan_count"] >= 1


def test_quality_report_computes_compile_observability_metrics(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    for index in range(3):
        capture_service.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-complete-{index}",
                topic="observability",
                problem_cluster="complete",
                content=f"# Raw complete {index}",
                source_refs=[],
            ),
        )
    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-incomplete-1",
            topic="observability",
            problem_cluster="incomplete",
            content="# Raw incomplete",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-complete-1",
            page_type="atom",
            topic="observability",
            problem_cluster="complete",
            summary="Complete metadata",
            aliases=["complete"],
            confidence="high",
            wikilinks=["raw-complete-0"],
            content="# Complete atom",
            source_refs=["personal-1:raw-complete-0"],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-incomplete-1",
            page_type="atom",
            topic="observability",
            problem_cluster="incomplete",
            content="# Incomplete atom",
            source_refs=["personal-1:raw-incomplete-1"],
        ),
    )
    (temp_wiki_root / "review_queue.jsonl").write_text(
        "\n".join(
            [
                json.dumps({
                    "item_id": "compile_suggestion:one",
                    "item_type": "compile_suggestion",
                    "status": "resolved",
                    "content_state": {"latency_seconds": 10.0},
                }),
                json.dumps({
                    "item_id": "compile_suggestion:two",
                    "item_type": "compile_suggestion",
                    "status": "failed",
                    "content_state": {"latency_seconds": 20.0, "error_type": "timeout"},
                }),
                json.dumps({
                    "item_id": "compile_suggestion:three",
                    "item_type": "compile_suggestion",
                    "status": "failed",
                    "content_state": {"error_type": "doc_id_error"},
                }),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = QualityReportService().generate(wiki)

    assert abs(report["compile_failure_rate"] - (2 / 3)) < 0.01
    assert report["compile_failure_breakdown"] == {"timeout": 1, "doc_id_error": 1}
    assert report["avg_compile_latency_seconds"] == 15.0
    assert report["metadata_completeness"] == 0.5
    assert report["cluster_coverage"] == 1.0
    assert report["mature_cluster_coverage"] == 1.0


def test_quality_report_includes_relation_confidence_stats(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "knowledge_graph.jsonl").write_text(
        "".join(
            json.dumps(entry, ensure_ascii=False) + "\n"
            for entry in [
                {"subject": "A", "relation": "depends_on", "object": "B", "source_doc_id": "raw-a", "confidence_label": "EXTRACTED"},
                {"subject": "C", "relation": "depends_on", "object": "D", "source_doc_id": "raw-c", "confidence_label": "INFERRED"},
                {"subject": "E", "relation": "depends_on", "object": "F", "source_doc_id": "raw-e", "confidence_label": "AMBIGUOUS"},
            ]
        ),
        encoding="utf-8",
    )
    (temp_wiki_root / "review_queue.jsonl").write_text(
        json.dumps({"item_id": "relation_review:E:F:depends_on", "item_type": "relation_review", "status": "open"}) + "\n",
        encoding="utf-8",
    )

    report = QualityReportService().generate(wiki)

    assert report["relation_stats"] == {
        "total": 3,
        "extracted": 1,
        "inferred": 1,
        "ambiguous": 1,
        "pending_review": 1,
    }
