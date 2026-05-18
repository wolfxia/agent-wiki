from pathlib import Path
import os
import time

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.application.sync import SyncInput, SyncService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.adapters.plain_markdown import PlainMarkdownAdapter
from agent_wiki.infrastructure.adapters.obsidian import ObsidianAdapter


def test_sync_status_reports_workspace_files(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    sync_service = SyncService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-sync-1",
            topic="testing",
            problem_cluster="cluster-s1",
            content="# Raw sync one",
            source_refs=[],
        ),
    )

    result = sync_service.execute(wiki, actor, SyncInput(mode="status"))

    assert result.mode == "status"
    assert any(path.endswith("pages/raw-sync-1.md") for path in result.changed_files)




def test_sync_pull_view_updates_retrieval_index_for_query(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-query-vault"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "retrieval-note.md").write_text(
        "# Retrieval Note\n\nPull view content should become queryable.",
        encoding="utf-8",
    )

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    SyncService().execute(wiki, actor, SyncInput(mode="pull-view"))
    result = QueryService().execute(wiki=wiki, actor=actor, data=QueryInput(query="pull view content queryable"))

    assert result.hit_count >= 1
    assert result.hits[0].doc_id == "obsidian-query-vault_retrieval-note"

def test_sync_pull_view_imports_external_markdown(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    sync_service = SyncService()
    external_dir = temp_wiki_root / "external"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "imported.md").write_text("# Imported\n\nExternal content.", encoding="utf-8")

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    result = sync_service.execute(wiki, ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"), SyncInput(mode="pull-view"))

    assert result.mode == "pull-view"
    assert (temp_wiki_root / "pages" / "external_imported.md").exists()


def test_sync_pull_view_skips_unchanged_files_after_successful_pull(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "incremental-vault"
    external_dir.mkdir(exist_ok=True)
    note = external_dir / "incremental-note.md"
    note.write_text("# Incremental\n\nFirst version.", encoding="utf-8")

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    sync_service = SyncService()

    first = sync_service.execute(wiki, actor, SyncInput(mode="pull-view"))
    second = sync_service.execute(wiki, actor, SyncInput(mode="pull-view"))

    assert "pages/incremental-vault_incremental-note.md" in first.changed_files
    assert second.changed_files == []

    state_path = temp_wiki_root / ".agent-wiki" / "pull_view_state.json"
    last_sync_time = state_path.stat().st_mtime
    time.sleep(0.01)
    note.write_text("# Incremental\n\nSecond version.", encoding="utf-8")
    os.utime(note, (last_sync_time + 1, last_sync_time + 1))

    third = sync_service.execute(wiki, actor, SyncInput(mode="pull-view"))

    assert third.changed_files == ["pages/incremental-vault_incremental-note.md"]
    assert (temp_wiki_root / "pages" / "incremental-vault_incremental-note.md").read_text(encoding="utf-8") == "# Incremental\n\nSecond version."


def test_sync_pull_view_does_not_rebuild_retrieval_index(temp_wiki_root: Path, monkeypatch) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "no-rebuild-vault"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "note.md").write_text("# No Rebuild", encoding="utf-8")
    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    def fail_rebuild(self, wiki):
        raise AssertionError("pull-view should not rebuild retrieval index")

    monkeypatch.setattr(SyncService, "_rebuild_retrieval_index", fail_rebuild)

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="pull-view"),
    )

    assert result.changed_files == ["pages/no-rebuild-vault_note.md"]


def test_sync_push_view_exports_only_requested_doc_ids(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "one.md").write_text("# One", encoding="utf-8")
    (pages_dir / "two.md").write_text("# Two", encoding="utf-8")
    external_dir = temp_wiki_root / "vault"
    external_dir.mkdir(exist_ok=True)
    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="push-view", doc_ids=["one"]),
    )

    assert (external_dir / "one.md").exists()
    assert not (external_dir / "two.md").exists()
    assert any(path.endswith("one.md") for path in result.changed_files)


def test_sync_push_view_exports_workspace_markdown(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    sync_service = SyncService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    external_dir = temp_wiki_root / "external"
    external_dir.mkdir(exist_ok=True)

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-sync-2",
            topic="testing",
            problem_cluster="cluster-s2",
            content="# Raw sync two",
            source_refs=[],
        ),
    )

    result = sync_service.execute(wiki, actor, SyncInput(mode="push-view"))

    assert result.mode == "push-view"
    assert (external_dir / "raw-sync-2.md").exists()


def test_plain_markdown_adapter_reads_file(temp_wiki_root: Path) -> None:
    source = temp_wiki_root / "external-read.md"
    source.write_text("# Imported\n\nExternal content.", encoding="utf-8")

    document = PlainMarkdownAdapter().read(str(source))

    assert document["content"] == "# Imported\n\nExternal content."
    assert document["adapter_metadata"]["path"] == str(source)
    assert document["adapter_metadata"]["stem"] == "external-read"


def test_plain_markdown_adapter_writes_file(temp_wiki_root: Path) -> None:
    target = temp_wiki_root / "output.md"
    document = {"content": "# Written\n\nAdapter output."}

    PlainMarkdownAdapter().write(str(target), document)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "# Written\n\nAdapter output."


def test_obsidian_adapter_reads_frontmatter(temp_wiki_root: Path) -> None:
    source = temp_wiki_root / "note.md"
    source.write_text(
        "---\ntags:\n  - python\n  - wiki\naliases: [aw]\n---\n# Note Title\n\nBody content.",
        encoding="utf-8",
    )

    document = ObsidianAdapter().read(str(source))

    assert document["content"] == "# Note Title\n\nBody content."
    assert document["adapter_metadata"]["frontmatter"]["tags"] == ["python", "wiki"]
    assert document["adapter_metadata"]["frontmatter"]["aliases"] == ["aw"]
    assert document["adapter_metadata"]["path"] == str(source)


def test_obsidian_adapter_reads_file_without_frontmatter(temp_wiki_root: Path) -> None:
    source = temp_wiki_root / "plain-note.md"
    source.write_text("# Plain\n\nNo frontmatter here.", encoding="utf-8")

    document = ObsidianAdapter().read(str(source))

    assert document["content"] == "# Plain\n\nNo frontmatter here."
    assert document["adapter_metadata"]["frontmatter"] == {}


def test_obsidian_adapter_writes_with_frontmatter(temp_wiki_root: Path) -> None:
    target = temp_wiki_root / "written-note.md"
    document = {
        "content": "# Written\n\nBody content.",
        "adapter_metadata": {
            "frontmatter": {"tags": ["python", "wiki"], "aliases": ["aw"]},
        },
    }

    ObsidianAdapter().write(str(target), document)

    result = target.read_text(encoding="utf-8")
    assert result.startswith("---\n")
    assert "tags:" in result
    assert "# Written\n\nBody content." in result

    roundtrip = ObsidianAdapter().read(str(target))
    assert roundtrip["content"] == "# Written\n\nBody content."
    assert roundtrip["adapter_metadata"]["frontmatter"]["tags"] == ["python", "wiki"]


def test_obsidian_adapter_writes_without_frontmatter(temp_wiki_root: Path) -> None:
    target = temp_wiki_root / "no-fm-note.md"
    document = {"content": "# No FM\n\nJust content."}

    ObsidianAdapter().write(str(target), document)

    result = target.read_text(encoding="utf-8")
    assert result == "# No FM\n\nJust content."


def test_sync_pull_uses_obsidian_adapter_for_obsidian_view(temp_wiki_root: Path) -> None:
    """Obsidian pull normalizes content via adapter (strips frontmatter into internal pages)."""
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-vault"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "obs-note.md").write_text(
        "---\ntags:\n  - imported\n---\n# Obsidian Note\n\nVault content.",
        encoding="utf-8",
    )

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    result = SyncService().execute(wiki, ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"), SyncInput(mode="pull-view"))

    assert result.mode == "pull-view"
    imported = temp_wiki_root / "pages" / "obsidian-vault_obs-note.md"
    assert imported.exists()
    content = imported.read_text(encoding="utf-8")
    # Adapter dispatch should store only the content body in workspace pages
    assert content == "# Obsidian Note\n\nVault content."
    assert "---" not in content


def test_sync_push_uses_obsidian_adapter_preserves_frontmatter(temp_wiki_root: Path) -> None:
    """Obsidian push writes back with frontmatter from adapter_metadata."""
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-vault"
    external_dir.mkdir(exist_ok=True)

    # Pre-existing obsidian file with frontmatter
    (external_dir / "existing.md").write_text(
        "---\ntags:\n  - wiki\n---\n# Existing\n\nOld content.",
        encoding="utf-8",
    )

    # Workspace page (modified content)
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "existing.md").write_text("# Existing\n\nNew content.", encoding="utf-8")

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    result = SyncService().execute(wiki, ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"), SyncInput(mode="push-view"))

    assert result.mode == "push-view"
    pushed = external_dir / "existing.md"
    content = pushed.read_text(encoding="utf-8")
    # Should preserve frontmatter from original external file
    assert "tags:" in content
    assert "# Existing\n\nNew content." in content


def test_sync_pull_creates_pending_manifest_entry(temp_wiki_root: Path) -> None:
    """Pulling a new external file creates a pending manifest entry for lifecycle visibility."""
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "external"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "new-note.md").write_text("# New Note\n\nExternal content.", encoding="utf-8")

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    SyncService().execute(wiki, ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"), SyncInput(mode="pull-view"))

    pending_path = temp_wiki_root / ".agent-wiki" / "pending_manifest.jsonl"
    assert pending_path.exists()
    entries = [json.loads(line) for line in pending_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(e["doc_id"] == "external_new-note" for e in entries)
    entry = next(e for e in entries if e["doc_id"] == "external_new-note")
    assert entry["page_type"] == "raw"
    assert entry["source"] == "external_sync"



def test_sync_pull_view_requires_permission(temp_wiki_root: Path) -> None:
    from agent_wiki.bootstrap.registry_loader import PermissionConfig

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={
            "workspace_path": str(temp_wiki_root),
            "permissions": [
                PermissionConfig(
                    actor_type="agent",
                    actor_id="no-sync-agent",
                    allowed_operations=["query"],
                    max_gate="A",
                    allowed_page_types=["raw"],
                )
            ],
        }
    )
    external_dir = temp_wiki_root / "external"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "blocked.md").write_text("# Blocked", encoding="utf-8")
    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    try:
        SyncService().execute(
            wiki,
            ResolvedActor(actor_type="agent", actor_id="no-sync-agent", transport="cli"),
            SyncInput(mode="pull-view"),
        )
    except PermissionError as error:
        assert "permission" in str(error).lower() or "no matching" in str(error).lower()
    else:
        raise AssertionError("expected sync permission failure")



def test_sync_push_skips_read_only_external_view(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    external_dir = temp_wiki_root / "external-read-only"
    external_dir.mkdir(exist_ok=True)

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_only", "path": str(external_dir)}
            ]
        }
    )

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-sync-read-only",
            topic="testing",
            problem_cluster="cluster-sync-ro",
            content="# Read only sync",
            source_refs=[],
        ),
    )

    result = SyncService().execute(wiki, actor, SyncInput(mode="push-view"))

    assert result.mode == "push-view"
    assert result.changed_files == []
    assert not (external_dir / "raw-sync-read-only.md").exists()


def test_sync_push_view_requires_sync_permission(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "external-sync-blocked"
    external_dir.mkdir(exist_ok=True)
    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    try:
        SyncService().execute(
            wiki,
            ResolvedActor(actor_type="agent", actor_id="codex", transport="cli"),
            SyncInput(mode="push-view"),
        )
    except PermissionError as error:
        assert "permission" in str(error).lower() or "no matching" in str(error).lower()
    else:
        raise AssertionError("expected sync permission failure")


def test_sync_push_view_rebuilds_obsidian_graph_index(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    external_dir = temp_wiki_root / "obsidian-vault"
    external_dir.mkdir(exist_ok=True)
    wiki = wiki.model_copy(update={"external_views": [{"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}]})

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(doc_id="raw-graph-1", topic="retrieval", problem_cluster="cluster-graph", content="# Raw graph", source_refs=[]),
    )
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(doc_id="raw-graph-2", topic="retrieval", problem_cluster="cluster-graph", content="# Raw graph 2", source_refs=[]),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(doc_id="atom-graph-1", page_type="atom", topic="retrieval", problem_cluster="cluster-graph", content="# Atom graph", source_refs=["personal-1:raw-graph-1"]),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(doc_id="synthesis-graph-1", page_type="synthesis", topic="retrieval", problem_cluster="cluster-graph", content="# Synth graph", source_refs=["personal-1:raw-graph-2"]),
    )

    result = SyncService().execute(wiki, actor, SyncInput(mode="push-view"))

    index_path = external_dir / "knowledge-graph" / "index.md"
    assert index_path.exists()
    text = index_path.read_text(encoding="utf-8")
    assert "## Atom" in text
    assert "## Synthesis" in text
    assert "## Raw" in text
    assert "[[atom-graph-1]]" in text
    assert "[[synthesis-graph-1]]" in text
    assert "[[raw-graph-1]]" in text or "[[raw-graph-2]]" in text
    assert any(path.endswith("knowledge-graph/index.md") for path in result.changed_files)


def test_compile_update_does_not_push_external_view(temp_wiki_root: Path) -> None:
    from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "vault-decouple"
    external_dir.mkdir(exist_ok=True)
    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-decouple-1",
            topic="testing",
            problem_cluster="cluster-decouple",
            content="# Raw decouple",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-decouple-1",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-decouple",
            content="# Atom decouple",
            source_refs=["personal-1:raw-decouple-1"],
        ),
    )

    assert not (external_dir / "atom-decouple-1.md").exists()


def test_obsidian_push_view_preserves_frontmatter_and_reports_index_file(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    external_dir = temp_wiki_root / "obsidian-vault-compat"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "existing.md").write_text("---\ntags:\n  - wiki\n---\n# Existing\n", encoding="utf-8")
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "existing.md").write_text("# Existing\n\nNew content.", encoding="utf-8")
    wiki = wiki.model_copy(update={"external_views": [{"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}]})

    result = SyncService().execute(wiki, actor, SyncInput(mode="push-view", doc_ids=["existing"]))

    assert any(path.endswith("knowledge-graph/index.md") for path in result.changed_files)
    assert "tags:" in (external_dir / "existing.md").read_text(encoding="utf-8")



def test_sync_pull_view_recurses_subdirectories_and_skips_obsidian_system_dirs(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-recursive-vault"
    (external_dir / "01-学习笔记" / "端侧AI").mkdir(parents=True, exist_ok=True)
    (external_dir / ".obsidian").mkdir(exist_ok=True)
    (external_dir / ".trash").mkdir(exist_ok=True)

    (external_dir / "01-学习笔记" / "端侧AI" / "deep-note.md").write_text("# Deep Note\n\nRecursive pull should find me.", encoding="utf-8")
    (external_dir / ".obsidian" / "ignore-me.md").write_text("# Ignore", encoding="utf-8")
    (external_dir / ".trash" / "trash-me.md").write_text("# Trash", encoding="utf-8")

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="pull-view"),
    )

    pending_path = temp_wiki_root / ".agent-wiki" / "pending_manifest.jsonl"
    entries = [json.loads(line) for line in pending_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert result.mode == "pull-view"
    assert (temp_wiki_root / "pages" / "01-学习笔记_端侧AI_deep-note.md").exists()
    assert not (temp_wiki_root / "pages" / "ignore-me.md").exists()
    assert not (temp_wiki_root / "pages" / "trash-me.md").exists()
    assert any(entry["doc_id"] == "01-学习笔记_端侧AI_deep-note" for entry in entries)



def test_sync_pull_view_preserves_vault_relative_path_in_pending_manifest(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-structured-vault"
    nested_dir = external_dir / "02-行业洞察" / "AI基础设施"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "infra-note.md").write_text("# Infra Note\n\nKeep my vault-relative path.", encoding="utf-8")

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

    pending_path = temp_wiki_root / ".agent-wiki" / "pending_manifest.jsonl"
    entries = [json.loads(line) for line in pending_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entry = next(item for item in entries if item["doc_id"] == "02-行业洞察_AI基础设施_infra-note")

    assert entry["vault_relative_path"] == "02-行业洞察/AI基础设施/infra-note.md"



def test_sync_push_view_routes_obsidian_export_to_saved_vault_relative_path(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-push-vault"
    external_dir.mkdir(exist_ok=True)
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "routed-note.md").write_text("# Routed Note\n\nPush me back to my saved subdir.", encoding="utf-8")

    manifest_path = temp_wiki_root / "MANIFEST.jsonl"
    manifest_path.write_text(
        json.dumps(
            {
                "doc_id": "routed-note",
                "page_type": "atom",
                "canonical_uri": "pages/routed-note.md",
                "vault_relative_path": "02-行业洞察/AI基础设施/routed-note.md",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="push-view", doc_ids=["routed-note"]),
    )

    expected = external_dir / "02-行业洞察" / "AI基础设施" / "routed-note.md"
    assert expected.exists()
    assert any(path.endswith("02-行业洞察/AI基础设施/routed-note.md") for path in result.changed_files)



def test_sync_push_view_skips_plain_markdown_view_without_path(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "skip-none-path.md").write_text("# Skip None Path", encoding="utf-8")
    external_dir = temp_wiki_root / "obsidian-with-path"
    external_dir.mkdir(exist_ok=True)

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "plain_markdown", "mode": "read_write", "path": None},
                {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)},
            ]
        }
    )

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="push-view", doc_ids=["skip-none-path"]),
    )

    assert result.mode == "push-view"
    assert (external_dir / "skip-none-path.md").exists()
    assert not (temp_wiki_root / "None").exists()



def test_sync_pull_view_deduplicates_by_target_path(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    obsidian_dir = temp_wiki_root / "obsidian-dup"
    markdown_dir = temp_wiki_root / "plain-dup"
    obsidian_dir.mkdir(exist_ok=True)
    markdown_dir.mkdir(exist_ok=True)
    (obsidian_dir / "dup-note.md").write_text("# Duplicate\n\nFrom obsidian.", encoding="utf-8")
    (markdown_dir / "dup-note.md").write_text("# Duplicate\n\nFrom plain markdown.", encoding="utf-8")

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "obsidian", "mode": "read_write", "path": str(obsidian_dir)},
                {"adapter": "plain_markdown", "mode": "read_write", "path": str(markdown_dir)},
            ]
        }
    )

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="pull-view"),
    )

    assert (temp_wiki_root / "pages" / "obsidian-dup_dup-note.md").exists()
    assert (temp_wiki_root / "pages" / "plain-dup_dup-note.md").exists()
    assert "pages/obsidian-dup_dup-note.md" in result.changed_files
    assert "pages/plain-dup_dup-note.md" in result.changed_files


def test_obsidian_adapter_reads_frontmatter_for_intake(temp_wiki_root: Path) -> None:
    note = temp_wiki_root / "frontmatter-note.md"
    note.write_text(
        "---\ntopic: deployment\nsummary: note summary\nclassification_confidence: high\n---\n# Frontmatter Note\n\nBody.",
        encoding="utf-8",
    )

    document = ObsidianAdapter().read(str(note))

    assert document["adapter_metadata"]["frontmatter"]["topic"] == "deployment"
    assert document["adapter_metadata"]["frontmatter"]["summary"] == "note summary"



def test_sync_pull_view_consumes_obsidian_frontmatter(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-frontmatter-vault"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "frontmatter-topic.md").write_text(
        "---\ntopic: frontmatter-topic\nproblem_cluster: frontmatter-cluster\nsummary: note summary\nclassification_confidence: high\n---\n# Frontmatter Topic\n\nImported content.",
        encoding="utf-8",
    )

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

    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    assert "frontmatter-topic" in manifest
    assert "frontmatter-cluster" in manifest
    assert "classification_confidence" in manifest
    assert "note summary" in manifest



def test_sync_pull_view_slugifies_relative_path_for_same_name_files(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "vault"
    (external_dir / "agent-os").mkdir(parents=True)
    (external_dir / "research").mkdir(parents=True)
    (external_dir / "agent-os" / "2026-04-15_MCP协议.md").write_text("# Agent OS MCP", encoding="utf-8")
    (external_dir / "research" / "2026-04-15_MCP协议.md").write_text("# Research MCP", encoding="utf-8")

    wiki = wiki.model_copy(
        update={
            "external_views": [
                {"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}
            ]
        }
    )

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="pull-view"),
    )

    assert (temp_wiki_root / "pages" / "agent-os_2026-04-15_MCP协议.md").exists()
    assert (temp_wiki_root / "pages" / "research_2026-04-15_MCP协议.md").exists()
    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    assert '"doc_id": "agent-os_2026-04-15_MCP协议"' in manifest
    assert '"doc_id": "research_2026-04-15_MCP协议"' in manifest
    assert '"vault_relative_path": "agent-os/2026-04-15_MCP协议.md"' in manifest
    assert '"vault_relative_path": "research/2026-04-15_MCP协议.md"' in manifest
    assert "pages/agent-os_2026-04-15_MCP协议.md" in result.changed_files
    assert "pages/research_2026-04-15_MCP协议.md" in result.changed_files


def test_sync_push_view_recurses_workspace_pages_and_routes_to_obsidian_categories(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-category-vault"
    external_dir.mkdir(exist_ok=True)
    pages_dir = temp_wiki_root / "pages"
    (pages_dir / "nested" / "learning").mkdir(parents=True, exist_ok=True)
    (pages_dir / "raw-agent.md").write_text("# Raw Agent\n\nInbox content.", encoding="utf-8")
    (pages_dir / "nested" / "learning" / "atom-agent.md").write_text("# Atom Agent\n\nLearning content.", encoding="utf-8")
    (pages_dir / "synthesis-industry.md").write_text("# Synthesis Industry\n\nInsight content.", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"wiki_id": "personal-1", "doc_id": "raw-agent", "page_type": "raw", "topic": "inbox", "problem_cluster": "capture", "summary": "raw", "canonical_uri": "pages/raw-agent.md"}, ensure_ascii=False),
                json.dumps({"wiki_id": "personal-1", "doc_id": "atom-agent", "page_type": "atom", "topic": "edge-ai-imaging", "problem_cluster": "edge-ai-imaging", "summary": "atom", "canonical_uri": "pages/nested/learning/atom-agent.md"}, ensure_ascii=False),
                json.dumps({"wiki_id": "personal-1", "doc_id": "synthesis-industry", "page_type": "synthesis", "topic": "行业洞察", "problem_cluster": "AI基础设施", "summary": "synthesis", "canonical_uri": "pages/synthesis-industry.md"}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    wiki = wiki.model_copy(update={"external_views": [{"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}]})

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="push-view"),
    )

    assert (external_dir / "raw" / "raw-agent.md").exists()
    assert (external_dir / "atoms" / "atom-agent.md").exists()
    assert (external_dir / "synthesis" / "AI基础设施" / "synthesis-industry.md").exists()
    assert (external_dir / "knowledge-graph" / "index.md").exists()
    assert any(path.endswith("atoms/atom-agent.md") for path in result.changed_files)



def test_sync_push_view_uses_configured_obsidian_routing(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-configured-vault"
    external_dir.mkdir(exist_ok=True)
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "raw-agent.md").write_text("# Raw Agent", encoding="utf-8")
    (pages_dir / "atom-agent.md").write_text("# Atom Agent", encoding="utf-8")
    (pages_dir / "synthesis-industry.md").write_text("# Synthesis Industry", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"wiki_id": "personal-1", "doc_id": "raw-agent", "page_type": "raw", "topic": "inbox", "problem_cluster": "capture", "canonical_uri": "pages/raw-agent.md"}, ensure_ascii=False),
                json.dumps({"wiki_id": "personal-1", "doc_id": "atom-agent", "page_type": "atom", "topic": "edge-ai-imaging", "problem_cluster": "edge-ai-imaging", "canonical_uri": "pages/atom-agent.md"}, ensure_ascii=False),
                json.dumps({"wiki_id": "personal-1", "doc_id": "synthesis-industry", "page_type": "synthesis", "topic": "行业洞察", "problem_cluster": "AI基础设施", "canonical_uri": "pages/synthesis-industry.md"}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    wiki = wiki.model_copy(
        update={
            "external_views": [
                {
                    "adapter": "obsidian",
                    "mode": "read_write",
                    "path": str(external_dir),
                    "push_view_routing": {
                        "direction_folders": {"edge-ai-imaging": "edge-ai-imaging"},
                        "fallback_folders": {"raw": "00-收件箱", "synthesis": "02-行业洞察", "atom": "01-学习笔记"},
                        "graph_index_folder": "04-知识图谱",
                        "graph_index_title": "知识图谱索引",
                    },
                }
            ]
        }
    )

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="push-view"),
    )

    assert (external_dir / "00-收件箱" / "raw-agent.md").exists()
    assert (external_dir / "edge-ai-imaging" / "atom-agent.md").exists()
    assert (external_dir / "02-行业洞察" / "AI基础设施" / "synthesis-industry.md").exists()
    assert (external_dir / "04-知识图谱" / "index.md").exists()
    assert "# 知识图谱索引" in (external_dir / "04-知识图谱" / "index.md").read_text(encoding="utf-8")
    assert any(path.endswith("edge-ai-imaging/atom-agent.md") for path in result.changed_files)

def test_sync_push_view_exports_all_manifest_pages_even_when_pages_are_nested(temp_wiki_root: Path) -> None:
    import json

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "obsidian-all-pages-vault"
    external_dir.mkdir(exist_ok=True)
    pages_dir = temp_wiki_root / "pages"
    for index in range(5):
        target_dir = pages_dir / "imported" / str(index % 2)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / f"doc-{index}.md").write_text(f"# Doc {index}", encoding="utf-8")
    manifest_lines = [
        json.dumps(
            {
                "wiki_id": "personal-1",
                "doc_id": f"doc-{index}",
                "page_type": "raw" if index == 0 else "atom",
                "topic": "学习笔记",
                "problem_cluster": "批量导出",
                "summary": f"doc {index}",
                "canonical_uri": f"pages/imported/{index % 2}/doc-{index}.md",
            },
            ensure_ascii=False,
        )
        for index in range(5)
    ]
    (temp_wiki_root / "MANIFEST.jsonl").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    wiki = wiki.model_copy(update={"external_views": [{"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}]})

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="push-view"),
    )

    exported_pages = [path for path in external_dir.rglob("*.md") if path.name != "index.md"]
    assert len(exported_pages) == 5
    assert len([path for path in result.changed_files if not path.endswith("knowledge-graph/index.md")]) == 5


def test_obsidian_adapter_sanitizes_yaml_dates_for_json_manifest(temp_wiki_root: Path) -> None:
    import json

    source = temp_wiki_root / "date-frontmatter.md"
    source.write_text(
        "---\ncreated: 2026-04-05\nnested:\n  reviewed: 2026-04-06\nitems:\n  - due: 2026-04-07\n---\n# Date Note\n",
        encoding="utf-8",
    )

    document = ObsidianAdapter().read(str(source))
    frontmatter = document["adapter_metadata"]["frontmatter"]

    assert frontmatter["created"] == "2026-04-05"
    assert frontmatter["nested"]["reviewed"] == "2026-04-06"
    assert frontmatter["items"][0]["due"] == "2026-04-07"
    json.dumps(document["adapter_metadata"])
