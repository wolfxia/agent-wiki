from pathlib import Path

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
