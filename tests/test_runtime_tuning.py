import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.application.runtime_tuning import RuntimeTuningService
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


def _seed_query_docs(wiki, actor) -> None:
    (Path(wiki.workspace_path) / "purpose.md").write_text(
        "# purpose\n\n## Topics\n- agent-os\n",
        encoding="utf-8",
    )
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-tuning-1",
            topic="agent-os",
            problem_cluster="tuning",
            content="# Raw tuning one",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-tuning-1",
            page_type="atom",
            topic="agent-os",
            problem_cluster="tuning",
            summary="Purpose aligned tuning doc.",
            aliases=["tuning"],
            confidence="high",
            wikilinks=["[[raw-tuning-1]]"],
            content="# Atom tuning\n\nPurpose aligned tuning doc.",
            source_refs=["personal-1:raw-tuning-1"],
        ),
    )


def test_query_uses_registry_tuning_defaults_when_runtime_file_missing(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    _seed_query_docs(wiki, actor)

    result = QueryService().execute(wiki=wiki, actor=actor, data=QueryInput(query="agent-os tuning"))

    assert result.hits[0].metadata["purpose_boost"] == 3.25
    assert result.hits[0].metadata["topic_alignment_boost"] == 6.5


def test_query_runtime_tuning_overrides_registry_defaults(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    _seed_query_docs(wiki, actor)
    runtime_root = temp_wiki_root / ".agent-wiki"
    runtime_root.mkdir(exist_ok=True)
    (runtime_root / "runtime_tuning.json").write_text(
        json.dumps({"query_ranking": {"purpose_boost": 9.75, "topic_alignment_boost": 1.5}}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = QueryService().execute(wiki=wiki, actor=actor, data=QueryInput(query="agent-os tuning"))

    assert result.hits[0].metadata["purpose_boost"] == 9.75
    assert result.hits[0].metadata["topic_alignment_boost"] == 1.5


def test_runtime_tuning_update_writes_history_and_freezes_baseline(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    service = RuntimeTuningService()

    updated = service.update_parameter(
        wiki=wiki,
        parameter_name="query_ranking.purpose_boost",
        new_value=4.5,
        trigger="manual",
        expected_effect="improve purpose ranking",
        eval_before={"strict_recall_at_k": 0.41},
    )
    baseline = service.freeze_baseline(wiki)

    assert updated.query_ranking.purpose_boost == 4.5
    runtime = json.loads((temp_wiki_root / ".agent-wiki" / "runtime_tuning.json").read_text(encoding="utf-8"))
    assert runtime["query_ranking"]["purpose_boost"] == 4.5

    history_path = temp_wiki_root / ".agent-wiki" / "param_history.jsonl"
    entries = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert entries[-1]["parameter_name"] == "query_ranking.purpose_boost"
    assert entries[-1]["old_value"] == 3.25
    assert entries[-1]["new_value"] == 4.5
    assert entries[-1]["trigger"] == "manual"
    assert entries[-1]["expected_effect"] == "improve purpose ranking"
    assert entries[-1]["eval_before"] == {"strict_recall_at_k": 0.41}

    frozen = json.loads((temp_wiki_root / ".agent-wiki" / "frozen_baseline.json").read_text(encoding="utf-8"))
    assert frozen == baseline.model_dump(mode="json")
