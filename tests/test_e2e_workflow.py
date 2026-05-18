import json
from pathlib import Path

import yaml

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.feedback import FeedbackInput, FeedbackService
from agent_wiki.application.linting import LintService
from agent_wiki.application.maintenance import MaintenanceService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.application.sync import SyncInput, SyncService
from agent_wiki.application.weekly_review import WeeklyReviewService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_e2e_workflow_from_capture_to_weekly_review(temp_wiki_root: Path) -> None:
    external_dir = temp_wiki_root / "e2e-obsidian-vault"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "atom-e2e-1.md").write_text(
        "---\ntags:\n  - preserved\n---\n# Existing view\n\nOld content.",
        encoding="utf-8",
    )

    registry_path = temp_wiki_root.parent / "registry-e2e.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["external_views"] = [
        {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
    ]
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    wiki = RegistryLoader().load(registry_path).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_result = CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-e2e-1",
            topic="deployment",
            problem_cluster="cluster-e2e",
            content="# Raw e2e one\n\nDeployment evidence.",
            source_refs=[],
        ),
    )
    assert capture_result.status == "committed"
    assert (temp_wiki_root / "pages" / "raw-e2e-1.md").exists()

    compile_result = CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-e2e-1",
            page_type="atom",
            topic="deployment",
            problem_cluster="cluster-e2e",
            content="# Atom e2e one\n\nDeployment workflow evidence compiled.",
            source_refs=["personal-1:raw-e2e-1"],
        ),
    )
    assert compile_result.status == "committed"
    assert (temp_wiki_root / "pages" / "atom-e2e-1.md").exists()

    query_result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="workflow evidence compiled"),
    )
    assert query_result.hit_count >= 1
    assert query_result.hits[0].doc_id == "atom-e2e-1"
    assert query_result.l3_proof[0]["source_refs"] == ["personal-1:raw-e2e-1"]

    lint_result = LintService().run(wiki)
    assert lint_result.ok is True
    assert lint_result.issues == []

    sync_result = SyncService().execute(
        wiki,
        actor,
        SyncInput(mode="push-view", doc_ids=["atom-e2e-1"]),
    )
    assert sync_result.mode == "push-view"
    exported = external_dir / "atom-e2e-1.md"
    assert exported.exists()
    exported_text = exported.read_text(encoding="utf-8")
    assert exported_text.startswith("---\n")
    assert "preserved" in exported_text
    assert (external_dir / "knowledge-graph" / "index.md").exists()

    feedback_result = FeedbackService().record(
        wiki,
        FeedbackInput(
            query_id="q-e2e-1",
            approved=False,
            missing_evidence=True,
            rewrite_targets=["atom-e2e-1"],
            notes="needs more deployment evidence",
        ),
    )
    assert feedback_result.created_review_item is True

    for i in range(2, 4):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-e2e-{i}",
                topic="deployment",
                problem_cluster="cluster-e2e",
                content=f"# Raw e2e {i}\n\nMore deployment evidence {i}.",
                source_refs=[],
            ),
        )

    gap_query = "qzxwvu987654"
    for _ in range(3):
        QueryService().execute(
            wiki=wiki,
            actor=actor,
            data=QueryInput(query=gap_query),
        )

    maintenance_summary = MaintenanceService().run(wiki)
    assert maintenance_summary["compile_suggestions"] >= 1
    assert maintenance_summary["quality_signals"] >= 1
    assert maintenance_summary["action_items"]

    queue_path = temp_wiki_root / "review_queue.jsonl"
    queue_entries = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    item_types = {entry.get("item_type") for entry in queue_entries}
    assert "feedback_issue" in item_types
    assert "compile_suggestion" in item_types
    assert "quality_signal" in item_types

    weekly_report = WeeklyReviewService().generate(wiki)
    assert "feedback events" in weekly_report.summary
    assert "miss signals" in weekly_report.summary
    assert "compile_suggestion" in weekly_report.summary
    assert "quality_signal" in weekly_report.summary
    assert any("needs more deployment evidence" in action for action in weekly_report.suggested_actions)
