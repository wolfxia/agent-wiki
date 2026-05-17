import json
from pathlib import Path

import yaml

from agent_wiki.application.compile_suggest import CompileSuggestService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.application.sync import SyncInput, SyncService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_phase1_foundation_closed_loop(temp_wiki_root: Path) -> None:
    external_dir = temp_wiki_root / "phase1-obsidian-vault"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "deploy" ).mkdir(exist_ok=True)
    (external_dir / "deploy" / "imported-raw-1.md").write_text(
        "---\ntopic: deployment\nproblem_cluster: canary-release\nsummary: Imported deployment evidence.\nclassification_confidence: high\n---\n# Imported Raw\n\nCanary rollout evidence from Obsidian.",
        encoding="utf-8",
    )

    registry_path = temp_wiki_root.parent / "registry-phase1-foundation.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text(encoding="utf-8"))
    registry_data["wikis"][0]["external_views"] = [
        {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
    ]
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    wiki = RegistryLoader().load(registry_path).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    pull_result = SyncService().execute(wiki, actor, SyncInput(mode="pull-view"))
    assert pull_result.mode == "pull-view"
    assert (temp_wiki_root / "pages" / "imported-raw-1.md").exists()

    manifest_entries = [
        json.loads(line)
        for line in (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    imported_entry = next(entry for entry in manifest_entries if entry["doc_id"] == "imported-raw-1")
    assert imported_entry["topic"] == "deployment"
    assert imported_entry["problem_cluster"] == "canary-release"
    assert imported_entry["summary"] == "Imported deployment evidence."

    suggestions = CompileSuggestService().detect(wiki, threshold=1)
    assert any(candidate["kind"] in {"undercompiled_cluster", "ready_to_compile"} for candidate in suggestions)

    compile_result = CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-foundation-1",
            page_type="atom",
            topic="deployment",
            problem_cluster="canary-release",
            summary="Preferred deployment answer.",
            aliases=["canary rollout"],
            confidence="high",
            contested=False,
            wikilinks=["imported-raw-1"],
            content="# Foundation Atom\n\nCompiled deployment guidance.",
            source_refs=["personal-1:imported-raw-1"],
        ),
    )
    assert compile_result.status == "committed"

    query_result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="preferred deployment answer"),
    )
    assert query_result.hit_count >= 1
    assert query_result.hits[0].doc_id == "atom-foundation-1"
    assert query_result.l1_answer == "Preferred deployment answer."

    topic_index_text = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
    assert "atom-foundation-1" in topic_index_text
    assert "Preferred deployment answer." in topic_index_text
