import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.linting import LintService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_lint_detects_missing_page_for_manifest_entry(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    lint_service = LintService()

    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        json.dumps(
            {
                "wiki_id": "personal-1",
                "doc_id": "raw-missing-page",
                "page_type": "raw",
                "canonical_uri": "pages/raw-missing-page.md",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = lint_service.run(wiki)

    assert result.ok is False
    assert any("missing page" in issue for issue in result.issues)


def test_lint_passes_for_basic_committed_capture(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    lint_service = LintService()

    capture_service.execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-lint-1",
            topic="testing",
            problem_cluster="cluster-l1",
            content="# Raw lint one",
            source_refs=[],
        ),
    )

    result = lint_service.run(wiki)

    assert result.ok is True
    assert result.issues == []


def test_lint_detects_stale_markers(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    repo = PendingStateRepository(temp_wiki_root)
    repo.append_stale_marker({
        "doc_id": "atom-stale-lint",
        "reason": "downstream propagation failed",
    })

    result = LintService().run(wiki)

    assert result.ok is False
    assert any("stale" in issue.lower() for issue in result.issues)



def test_lint_detects_missing_source_refs_on_compiled_page(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "atom-no-sources.md").write_text("# Atom no sources", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        json.dumps(
            {
                "wiki_id": "personal-1",
                "doc_id": "atom-no-sources",
                "page_type": "atom",
                "canonical_uri": "pages/atom-no-sources.md",
                "topic": "testing",
                "problem_cluster": "cluster-lint-src",
                "source_refs": [],
            }
        ) + "\n",
        encoding="utf-8",
    )

    result = LintService().run(wiki)

    assert result.ok is False
    assert any("source_refs" in issue for issue in result.issues)



def test_lint_passes_after_pull_view_promotes_raw_pages_to_manifest(temp_wiki_root: Path) -> None:
    from agent_wiki.application.sync import SyncInput, SyncService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "lint-pull-vault"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "pulled-lint-note.md").write_text("# Pulled Lint Note\n\nSuccessful pull-view imports should lint cleanly.", encoding="utf-8")

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="pull-view"),
    )

    result = LintService().run(wiki)

    assert result.ok is True
    assert result.issues == []


def test_lint_ignores_repaired_raw_pending_state(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.repair.raw_metadata_repair import RawMetadataRepairService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "repaired-raw-1.md").write_text("# Repaired Raw\n\nBody.", encoding="utf-8")
    pending_root = temp_wiki_root / ".agent-wiki"
    pending_root.mkdir(exist_ok=True)
    (pending_root / "pending_manifest.jsonl").write_text(
        json.dumps(
            {
                "doc_id": "repaired-raw-1",
                "page_type": "raw",
                "vault_relative_path": "repaired-raw-1.md",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    RawMetadataRepairService().repair(wiki)
    result = LintService().run(wiki)

    assert result.ok is True
    assert result.issues == []


def test_lint_detects_retrieval_index_missing_manifest_doc_and_recommends_rebuild(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "raw-index-missing.md").write_text("# Raw index missing", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        json.dumps(
            {
                "wiki_id": "personal-1",
                "doc_id": "raw-index-missing",
                "page_type": "raw",
                "topic": "ops",
                "problem_cluster": "index",
                "summary": "index missing",
                "canonical_uri": "pages/raw-index-missing.md",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (temp_wiki_root / "retrieval_index.jsonl").write_text("", encoding="utf-8")

    result = LintService().run(wiki)

    assert result.ok is False
    assert any("retrieval index missing manifest entry: raw-index-missing" in issue for issue in result.issues)
    assert any("rebuild retrieval indexes" in issue.lower() for issue in result.issues)


def test_lint_detects_fts_index_missing_manifest_doc_and_recommends_rebuild(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "raw-fts-missing.md").write_text("# Raw FTS missing", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        json.dumps(
            {
                "wiki_id": "personal-1",
                "doc_id": "raw-fts-missing",
                "page_type": "raw",
                "topic": "ops",
                "problem_cluster": "fts",
                "summary": "fts missing",
                "canonical_uri": "pages/raw-fts-missing.md",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (temp_wiki_root / "retrieval_index.jsonl").write_text(
        json.dumps({"wiki_id": "personal-1", "doc_id": "raw-fts-missing", "page_type": "raw", "content": "present"}) + "\n",
        encoding="utf-8",
    )

    result = LintService().run(wiki)

    assert result.ok is False
    assert any("fts index missing manifest entry: raw-fts-missing" in issue for issue in result.issues)
    assert any("rebuild retrieval indexes" in issue.lower() for issue in result.issues)


def test_raw_metadata_repair_rebuilds_runtime_indexes(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.repair.raw_metadata_repair import RawMetadataRepairService
    from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "repaired-index-1.md").write_text("# Repaired Index\n\nRepair searchable content.", encoding="utf-8")
    pending_root = temp_wiki_root / ".agent-wiki"
    pending_root.mkdir(exist_ok=True)
    (pending_root / "pending_manifest.jsonl").write_text(
        json.dumps({"doc_id": "repaired-index-1", "page_type": "raw", "vault_relative_path": "repaired-index-1.md"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    RawMetadataRepairService().repair(wiki)

    retrieval_text = (temp_wiki_root / "retrieval_index.jsonl").read_text(encoding="utf-8")
    fts_hits = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1").search("Repair searchable", top_k=5)
    lint_result = LintService().run(wiki)

    assert "repaired-index-1" in retrieval_text
    assert [hit.doc_id for hit in fts_hits] == ["repaired-index-1"]
    assert lint_result.ok is True
