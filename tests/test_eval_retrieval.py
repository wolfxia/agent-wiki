from pathlib import Path
import json

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.eval_retrieval import EvalRetrievalService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def _wiki(temp_wiki_root: Path):
    return RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )


def test_eval_retrieval_reports_quality_metrics_without_logging_queries(temp_wiki_root: Path, tmp_path: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-eval-1",
            topic="agent-os",
            problem_cluster="mcp-protocol",
            content="# MCP raw\n\nMCP sidecar communication evidence.",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-eval-1",
            page_type="atom",
            topic="agent-os",
            problem_cluster="mcp-protocol",
            summary="MCP sidecars let agents communicate with shared tools.",
            content="# MCP atom\n\nMCP sidecar communication for agent tools.",
            source_refs=["personal-1:raw-eval-1"],
        ),
    )
    eval_file = tmp_path / "retrieval_queries.jsonl"
    eval_file.write_text(
        json.dumps(
            {
                "query": "MCP sidecar communication",
                "query_type": "architecture",
                "expected_doc_ids": ["atom-eval-1"],
                "acceptable_doc_ids": ["raw-eval-1"],
                "must_not_doc_ids": ["missing-doc"],
                "notes": "fixture eval query",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = EvalRetrievalService().run(wiki=wiki, actor=actor, eval_file=eval_file, k=5)

    assert report["query_count"] == 1
    assert report["k"] == 5
    assert report["metrics"]["strict_recall_at_k"] == 1.0
    assert report["metrics"]["loose_recall_at_k"] == 1.0
    assert report["metrics"]["must_not_violation_at_k"] == 0.0
    assert report["metrics"]["precision_at_k"] > 0
    assert report["metrics"]["mrr"] == 1.0
    assert report["metrics"]["compiled_hit_ratio"] > 0
    assert report["latency_ms"]["avg"] >= 0
    assert report["queries"][0]["hits"][0]["doc_id"] == "atom-eval-1"
    assert report["queries"][0]["strict_recall_at_k"] == 1.0
    assert report["queries"][0]["loose_recall_at_k"] == 1.0
    assert report["queries"][0]["must_not_violation_at_k"] == 0.0
    assert not (temp_wiki_root / "query_outcomes.jsonl").exists()


def test_eval_retrieval_passes_page_type_filter_to_query_service(temp_wiki_root: Path, tmp_path: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-eval-filter-1",
            topic="agent-os",
            problem_cluster="filter",
            content="# Raw eval filter\n\nfilterable query target repeated filterable query target",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-eval-filter-1",
            page_type="atom",
            topic="agent-os",
            problem_cluster="filter",
            content="# Atom eval filter\n\nfilterable query target",
            source_refs=["personal-1:raw-eval-filter-1"],
        ),
    )
    eval_file = tmp_path / "retrieval_queries.jsonl"
    eval_file.write_text(
        json.dumps(
            {
                "query": "filterable query target",
                "query_type": "fact",
                "expected_doc_ids": ["atom-eval-filter-1"],
                "acceptable_doc_ids": [],
                "must_not_doc_ids": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = EvalRetrievalService().run(wiki=wiki, actor=actor, eval_file=eval_file, k=5, page_types=["atom"])

    assert [hit["doc_id"] for hit in report["queries"][0]["hits"]] == ["atom-eval-filter-1"]


def test_eval_retrieval_tracks_strict_loose_and_must_not_metrics_and_writes_history(temp_wiki_root: Path, tmp_path: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-history-1",
            topic="agent-os",
            problem_cluster="history",
            content="# Raw history\n\nMCP sidecar baseline evidence.",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-history-1",
            page_type="atom",
            topic="agent-os",
            problem_cluster="history",
            summary="Compiled MCP sidecar guidance.",
            confidence="high",
            aliases=["mcp sidecar"],
            wikilinks=["[[raw-history-1]]"],
            content="# Atom history\n\n## Claims\n- MCP sidecar guidance.\n\n## Evidence\n- Derived from raw notes.",
            source_refs=["personal-1:raw-history-1"],
        ),
    )

    eval_file = tmp_path / "retrieval_queries.jsonl"
    eval_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "query": "compiled MCP sidecar guidance",
                        "query_type": "architecture",
                        "expected_doc_ids": ["atom-history-1"],
                        "acceptable_doc_ids": ["raw-history-1"],
                        "must_not_doc_ids": ["missing-doc"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "query": "MCP sidecar guidance",
                        "query_type": "proof",
                        "expected_doc_ids": ["missing-doc"],
                        "acceptable_doc_ids": ["raw-history-1"],
                        "must_not_doc_ids": ["atom-history-1"],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    runtime_dir = temp_wiki_root / ".agent-wiki"
    runtime_dir.mkdir(exist_ok=True)
    (runtime_dir / "runtime_tuning.json").write_text(
        json.dumps({"query_ranking": {"purpose_boost": 2.0}}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = EvalRetrievalService().run(wiki=wiki, actor=actor, eval_file=eval_file, k=5)

    assert report["metrics"]["strict_recall_at_k"] == 0.5
    assert report["metrics"]["loose_recall_at_k"] == 1.0
    assert report["metrics"]["must_not_violation_at_k"] == 0.5
    assert report["queries"][0]["strict_recall_at_k"] == 1.0
    assert report["queries"][0]["loose_recall_at_k"] == 1.0
    assert report["queries"][0]["must_not_violation_at_k"] == 0.0
    assert report["queries"][1]["strict_recall_at_k"] == 0.0
    assert report["queries"][1]["loose_recall_at_k"] == 1.0
    assert report["queries"][1]["must_not_violation_at_k"] == 1.0

    history_path = runtime_dir / "eval_history.jsonl"
    assert history_path.exists()
    entries = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(entries) == 1
    history = entries[0]
    assert history["eval_file"] == str(eval_file)
    assert history["k"] == 5
    assert history["runtime_tuning"] == {"query_ranking": {"purpose_boost": 2.0}}
    assert history["metrics"] == {
        "strict_recall_at_k": 0.5,
        "loose_recall_at_k": 1.0,
        "must_not_violation_at_k": 0.5,
        "mrr": report["metrics"]["mrr"],
        "compiled_hit_ratio": report["metrics"]["compiled_hit_ratio"],
    }
    assert len(history["queries"]) == 2


def test_eval_retrieval_history_uses_defaults_when_runtime_tuning_missing(temp_wiki_root: Path, tmp_path: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-defaults-1",
            topic="agent-os",
            problem_cluster="defaults",
            content="# Raw defaults\n\nDefault tuning evidence.",
            source_refs=[],
        ),
    )
    eval_file = tmp_path / "retrieval_queries.jsonl"
    eval_file.write_text(
        json.dumps(
            {
                "query": "default tuning evidence",
                "query_type": "proof",
                "expected_doc_ids": ["raw-defaults-1"],
                "acceptable_doc_ids": [],
                "must_not_doc_ids": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    EvalRetrievalService().run(wiki=wiki, actor=actor, eval_file=eval_file, k=3)

    history_path = temp_wiki_root / ".agent-wiki" / "eval_history.jsonl"
    entries = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert entries[-1]["runtime_tuning"] == "defaults"
