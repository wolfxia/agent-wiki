import json
from pathlib import Path

from typer.testing import CliRunner

from agent_wiki.application.dream_cycle import DreamCycleService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.candidate_group import CandidateGroup
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository
from agent_wiki.transports.cli.app import app


def _wiki(temp_wiki_root: Path):
    return RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )


def _actor() -> ResolvedActor:
    return ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")


def _write_page(wiki_root: Path, doc_id: str, content: str) -> None:
    pages = wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / f"{doc_id}.md").write_text(content, encoding="utf-8")


def _manifest_upsert(wiki_root: Path, entry: dict) -> None:
    ManifestRepository(wiki_root).upsert(
        {
            "wiki_id": "personal-1",
            "canonical_uri": f"pages/{entry['doc_id']}.md",
            **entry,
        }
    )


def test_candidate_group_serializes_to_json_dict() -> None:
    group = CandidateGroup(
        atom_ids=["atom-a", "atom-b"],
        shared_keywords=["constraint"],
        graph_relations=["depends_on:latency"],
        strength=0.42,
    )

    assert group.to_dict() == {
        "atom_ids": ["atom-a", "atom-b"],
        "shared_keywords": ["constraint"],
        "graph_relations": ["depends_on:latency"],
        "strength": 0.42,
    }


def test_orphan_scan_reports_unqueued_raw_and_unreferenced_atom(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_page(temp_wiki_root, "raw-orphan-dream", "# Raw orphan\n\nEvidence.")
    _manifest_upsert(
        temp_wiki_root,
        {
            "doc_id": "raw-orphan-dream",
            "page_type": "raw",
            "topic": "ops",
            "problem_cluster": "dream-cycle",
            "summary": "raw orphan",
        },
    )
    _write_page(temp_wiki_root, "raw-queued-dream", "# Raw queued\n\nEvidence.")
    _manifest_upsert(
        temp_wiki_root,
        {
            "doc_id": "raw-queued-dream",
            "page_type": "raw",
            "topic": "ops",
            "problem_cluster": "dream-cycle",
            "summary": "queued raw",
        },
    )
    _write_page(temp_wiki_root, "atom-orphan-dream", "# Atom orphan\n\nCompiled claim.")
    _manifest_upsert(
        temp_wiki_root,
        {
            "doc_id": "atom-orphan-dream",
            "page_type": "atom",
            "topic": "ops",
            "problem_cluster": "dream-cycle",
            "summary": "atom orphan",
            "source_refs": [],
        },
    )
    ReviewQueueRepository(temp_wiki_root).append(
        {
            "item_id": "compile_suggestion:ops:dream-cycle:0001",
            "item_type": "compile_suggestion",
            "raw_doc_ids": ["raw-queued-dream"],
        }
    )

    report = DreamCycleService().orphan_scan(wiki)

    assert [(item["orphan_type"], item["doc_id"]) for item in report] == [
        ("raw", "raw-orphan-dream"),
        ("atom", "atom-orphan-dream"),
    ]
    report_path = temp_wiki_root / ".agent-wiki" / "dream_cycle_orphans.jsonl"
    stored = [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]
    assert [item["doc_id"] for item in stored] == ["raw-orphan-dream", "atom-orphan-dream"]
    assert all(item["first_seen"] for item in stored)


def test_orphan_scan_dry_run_does_not_write_report(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_page(temp_wiki_root, "raw-dry-run-dream", "# Raw\n")
    _manifest_upsert(
        temp_wiki_root,
        {
            "doc_id": "raw-dry-run-dream",
            "page_type": "raw",
            "topic": "ops",
            "problem_cluster": "dream-cycle",
            "summary": "raw",
        },
    )

    report = DreamCycleService().orphan_scan(wiki, dry_run=True)

    assert report[0]["doc_id"] == "raw-dry-run-dream"
    assert not (temp_wiki_root / ".agent-wiki" / "dream_cycle_orphans.jsonl").exists()


def test_synthesis_generate_writes_synthesis_from_atom_sources(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    for doc_id in ["atom-synth-a", "atom-synth-b"]:
        _write_page(temp_wiki_root, doc_id, f"# {doc_id}\n\nConstraint-first insight.")
        _manifest_upsert(
            temp_wiki_root,
            {
                "doc_id": doc_id,
                "page_type": "atom",
                "topic": "ops",
                "problem_cluster": "constraint-first",
                "summary": doc_id,
                "source_refs": [],
            },
        )

    def fake_llm(_wiki, group, atom_pages):
        assert group.atom_ids == ["atom-synth-a", "atom-synth-b"]
        assert set(atom_pages) == {"atom-synth-a", "atom-synth-b"}
        return "# Cross-domain Constraint First\n\nSynthesis generated from atom evidence."

    results = DreamCycleService(llm_generate=fake_llm).synthesis_generate(
        wiki,
        _actor(),
        [
            CandidateGroup(
                atom_ids=["atom-synth-a", "atom-synth-b"],
                shared_keywords=["constraint"],
                graph_relations=[],
                strength=0.7,
            )
        ],
    )

    assert len(results) == 1
    result = results[0]
    assert result["status"] == "committed"
    manifest_entry = ManifestRepository(temp_wiki_root).find(result["doc_id"])
    assert manifest_entry["page_type"] == "synthesis"
    assert manifest_entry["source_refs"] == ["personal-1:atom-synth-a", "personal-1:atom-synth-b"]
    content = (temp_wiki_root / "pages" / f"{result['doc_id']}.md").read_text(encoding="utf-8")
    assert "generated_by: dream-cycle" in content
    assert "source_atoms:" in content
    assert "# Cross-domain Constraint First" in content


def test_synthesis_generate_dry_run_returns_plan_without_writing(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    for doc_id in ["atom-plan-a", "atom-plan-b"]:
        _write_page(temp_wiki_root, doc_id, f"# {doc_id}\n")
        _manifest_upsert(
            temp_wiki_root,
            {
                "doc_id": doc_id,
                "page_type": "atom",
                "topic": "ops",
                "problem_cluster": "plan",
                "summary": doc_id,
                "source_refs": [],
            },
        )

    results = DreamCycleService().synthesis_generate(
        wiki,
        _actor(),
        [CandidateGroup(atom_ids=["atom-plan-a", "atom-plan-b"], shared_keywords=[], graph_relations=[], strength=0.8)],
        dry_run=True,
    )

    assert results[0]["status"] == "planned"
    assert not (temp_wiki_root / "pages" / f"{results[0]['doc_id']}.md").exists()


def test_cross_reference_skips_external_sync_atoms(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    for doc_id, topic in [
        ("atom-external-sync-a", "external_sync:A2A protocol deep dive"),
        ("atom-external-sync-b", "external_sync:HTTP agent collaboration"),
        ("atom-real-a", "agent-os"),
        ("atom-real-b", "ai-harness"),
    ]:
        _write_page(temp_wiki_root, doc_id, f"# {doc_id}\n\nconstraint scheduling")
        _manifest_upsert(
            temp_wiki_root,
            {
                "doc_id": doc_id,
                "page_type": "atom",
                "topic": topic,
                "problem_cluster": "constraint-first",
                "summary": doc_id,
                "keywords": ["constraint", "scheduling"],
                "source_refs": [],
            },
        )

    groups = DreamCycleService().cross_reference(wiki)

    assert groups
    assert all(not atom_id.startswith("atom-external-sync-") for group in groups for atom_id in group.atom_ids)


def test_cross_reference_applies_cross_topic_strength_boost(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_page(temp_wiki_root, "atom-topic-a", "# Atom A\n\nconstraint schedule")
    _manifest_upsert(
        temp_wiki_root,
        {
            "doc_id": "atom-topic-a",
            "page_type": "atom",
            "topic": "agent-os",
            "problem_cluster": "pc-a",
            "summary": "a",
            "keywords": ["constraint", "schedule"],
            "source_refs": [],
        },
    )
    _write_page(temp_wiki_root, "atom-topic-b", "# Atom B\n\nconstraint schedule")
    _manifest_upsert(
        temp_wiki_root,
        {
            "doc_id": "atom-topic-b",
            "page_type": "atom",
            "topic": "ai-harness",
            "problem_cluster": "pc-b",
            "summary": "b",
            "keywords": ["constraint", "schedule"],
            "source_refs": [],
        },
    )

    groups = DreamCycleService().cross_reference(wiki)

    assert len(groups) == 1
    assert groups[0].atom_ids == ["atom-topic-a", "atom-topic-b"]
    assert groups[0].strength >= 0.8


def test_cross_reference_filters_out_same_topic_pairs(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    for doc_id in ["atom-same-topic-a", "atom-same-topic-b"]:
        _write_page(temp_wiki_root, doc_id, f"# {doc_id}\n\nconstraint schedule")
        _manifest_upsert(
            temp_wiki_root,
            {
                "doc_id": doc_id,
                "page_type": "atom",
                "topic": "agent-os",
                "problem_cluster": "same-topic-cluster",
                "summary": doc_id,
                "keywords": ["constraint", "schedule"],
                "source_refs": [],
            },
        )

    groups = DreamCycleService().cross_reference(wiki)

    assert groups == []


def test_synthesis_generate_dry_run_skips_loading_atom_pages(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)

    class GuardedDreamCycleService(DreamCycleService):
        def _load_atom_pages(self, wiki_root, manifest, atom_ids):  # type: ignore[override]
            raise AssertionError("_load_atom_pages should not be called in dry_run")

    groups = [
        CandidateGroup(atom_ids=["atom-x-1", "atom-x-2"], shared_keywords=[], graph_relations=[], strength=0.9),
    ]

    results = GuardedDreamCycleService().synthesis_generate(wiki, _actor(), groups, dry_run=True)

    assert results[0]["status"] == "planned"


def test_quality_review_enqueues_frontmatter_stale_source_and_length_issues(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_page(temp_wiki_root, "atom-quality-dream", "# Tiny\n\nShort.")
    _manifest_upsert(
        temp_wiki_root,
        {
            "doc_id": "atom-quality-dream",
            "page_type": "atom",
            "topic": "ops",
            "problem_cluster": "quality",
            "summary": "tiny",
            "source_refs": ["personal-1:missing-source"],
            "updated": "2026-03-01T00:00:00Z",
        },
    )

    issues = DreamCycleService().quality_review(wiki)

    assert len(issues) == 1
    assert issues[0]["doc_id"] == "atom-quality-dream"
    assert set(issues[0]["issue_codes"]) >= {"missing_frontmatter", "stale", "broken_source_ref", "too_short"}
    queue_item = ReviewQueueRepository(temp_wiki_root).find("quality_review:atom-quality-dream")
    assert queue_item["item_type"] == "quality_review"
    assert "broken_source_ref" in queue_item["content_state"]["issue_codes"]


def test_run_full_dream_cycle_returns_step_summary(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_page(temp_wiki_root, "raw-run-dream", "# Raw\n\nEvidence.")
    _manifest_upsert(
        temp_wiki_root,
        {
            "doc_id": "raw-run-dream",
            "page_type": "raw",
            "topic": "ops",
            "problem_cluster": "run",
            "summary": "raw",
        },
    )

    summary = DreamCycleService().run(wiki, _actor(), dry_run=True)

    assert summary["orphan_count"] == 1
    assert summary["candidate_group_count"] == 0
    assert summary["synthesis_count"] == 0
    assert summary["quality_issue_count"] == 0


def test_cli_dream_cycle_orphan_step_outputs_summary(temp_wiki_root: Path) -> None:
    _write_page(temp_wiki_root, "raw-cli-dream", "# Raw\n")
    _manifest_upsert(
        temp_wiki_root,
        {
            "doc_id": "raw-cli-dream",
            "page_type": "raw",
            "topic": "ops",
            "problem_cluster": "cli",
            "summary": "raw",
        },
    )

    result = CliRunner().invoke(
        app,
        [
            "dream-cycle",
            "--step",
            "orphan",
            "--workspace",
            str(temp_wiki_root),
            "--registry",
            "tests/fixtures/registry.yaml",
        ],
        env={"AGENT_WIKI_ACTOR_TYPE": "agent", "AGENT_WIKI_ACTOR_ID": "claude-code"},
    )

    assert result.exit_code == 0
    assert "orphan_count=1" in result.stdout
