from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
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

    result = sync_service.execute(wiki, SyncInput(mode="status"))

    assert result.mode == "status"
    assert any(path.endswith("pages/raw-sync-1.md") for path in result.changed_files)


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

    result = sync_service.execute(wiki, SyncInput(mode="pull-view"))

    assert result.mode == "pull-view"
    assert (temp_wiki_root / "pages" / "imported.md").exists()


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

    result = sync_service.execute(wiki, SyncInput(mode="push-view"))

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
