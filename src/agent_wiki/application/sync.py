from pathlib import Path

from pydantic import BaseModel

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.adapters.obsidian import ObsidianAdapter
from agent_wiki.infrastructure.adapters.plain_markdown import PlainMarkdownAdapter
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class SyncInput(BaseModel):
    mode: str
    doc_ids: list[str] | None = None


class SyncResult(BaseModel):
    mode: str
    changed_files: list[str]


_ADAPTERS = {
    "plain_markdown": PlainMarkdownAdapter,
    "obsidian": ObsidianAdapter,
}


class SyncService:
    def execute(self, wiki: WikiConfig, actor: ResolvedActor, data: SyncInput) -> SyncResult:
        self._check_permission(actor, wiki)
        if data.mode == "status":
            return self._status(wiki)
        if data.mode == "pull-view":
            return self._pull_view(wiki, actor)
        if data.mode == "push-view":
            return self._push_view(wiki, data.doc_ids)
        raise ValueError(f"unsupported sync mode: {data.mode}")

    def _check_permission(self, actor: ResolvedActor, wiki: WikiConfig) -> None:
        decision = PermissionService().check(actor, "sync", wiki, "raw")
        if not decision.allowed:
            raise PermissionError(decision.reason)

    def _status(self, wiki: WikiConfig) -> SyncResult:
        wiki_root = Path(wiki.workspace_path)
        changed_files = [str(path.relative_to(wiki_root)) for path in (wiki_root / "pages").glob("*.md")]
        return SyncResult(mode="status", changed_files=changed_files)

    def _pull_view(self, wiki: WikiConfig, actor: ResolvedActor) -> SyncResult:
        wiki_root = Path(wiki.workspace_path)
        pages_root = wiki_root / "pages"
        pages_root.mkdir(exist_ok=True)
        pending = PendingStateRepository(wiki_root)
        changed_files: list[str] = []
        seen_targets: set[Path] = set()
        for view in wiki.external_views:
            if not self._view_allows_pull(view):
                continue
            view_path = self._view_path(view)
            if view_path is None:
                continue
            adapter = self._get_adapter(view)
            external_path = Path(view_path)
            for source in external_path.rglob("*.md"):
                if self._is_ignored_external_file(source, external_path):
                    continue
                target = pages_root / source.name
                if target in seen_targets:
                    continue
                document = adapter.read(str(source))
                target.write_text(document["content"], encoding="utf-8")
                changed_files.append(str(target.relative_to(wiki_root)))
                seen_targets.add(target)
                doc_id = source.stem
                vault_relative_path = str(source.relative_to(external_path))
                pending.append_pending_manifest({
                    "doc_id": doc_id,
                    "page_type": "raw",
                    "source": "external_sync",
                    "last_writer": actor.actor_id,
                    "vault_relative_path": vault_relative_path,
                    "adapter_metadata": {"vault_relative_path": vault_relative_path},
                })
        return SyncResult(mode="pull-view", changed_files=changed_files)

    def _push_view(self, wiki: WikiConfig, doc_ids: list[str] | None = None) -> SyncResult:
        wiki_root = Path(wiki.workspace_path)
        changed_files: list[str] = []
        manifest = ManifestRepository(wiki_root)
        for view in wiki.external_views:
            if not self._view_allows_push(view):
                continue
            view_path = self._view_path(view)
            if view_path is None:
                continue
            adapter = self._get_adapter(view)
            external_path = Path(view_path)
            external_path.mkdir(exist_ok=True)
            for source in self._iter_export_sources(wiki_root, doc_ids):
                target = self._resolve_export_target(external_path, source, manifest)
                target.parent.mkdir(parents=True, exist_ok=True)
                document: dict = {"content": source.read_text(encoding="utf-8")}
                if target.exists():
                    existing = adapter.read(str(target))
                    adapter_metadata = existing.get("adapter_metadata", {})
                    document["adapter_metadata"] = adapter_metadata
                adapter.write(str(target), document)
                changed_files.append(str(target))

            if self._view_adapter(view) == "obsidian":
                changed_files.append(self._write_obsidian_graph_index(wiki, external_path))

        return SyncResult(mode="push-view", changed_files=changed_files)

    def _write_obsidian_graph_index(self, wiki: WikiConfig, external_path: Path) -> str:
        manifest_entries = ManifestRepository(Path(wiki.workspace_path)).read_all()
        index_path = external_path / "04-知识图谱" / "知识图谱索引.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        content = ObsidianAdapter().render_graph_index(manifest_entries)
        index_path.write_text(content, encoding="utf-8")
        return str(index_path)

    def _iter_export_sources(self, wiki_root: Path, doc_ids: list[str] | None) -> list[Path]:
        pages_root = wiki_root / "pages"
        if not doc_ids:
            return sorted(pages_root.glob("*.md"))
        return [pages_root / f"{doc_id}.md" for doc_id in doc_ids if (pages_root / f"{doc_id}.md").exists()]

    def _resolve_export_target(self, external_root: Path, source: Path, manifest: ManifestRepository) -> Path:
        entry = manifest.find(source.stem)
        if entry is not None:
            relative_path = entry.get("vault_relative_path")
            if relative_path:
                return external_root / relative_path
        return external_root / source.name

    def _get_adapter(self, view: object) -> object:
        adapter_name = self._view_adapter(view)
        cls = _ADAPTERS.get(adapter_name, PlainMarkdownAdapter)
        return cls()

    def _view_path(self, view: object) -> str | None:
        if isinstance(view, dict):
            value = view.get("path")
        else:
            value = getattr(view, "path", None)
        if value is None:
            return None
        return str(value)

    def _is_ignored_external_file(self, source: Path, external_root: Path) -> bool:
        relative_parts = source.relative_to(external_root).parts[:-1]
        return any(part in {".obsidian", ".trash"} for part in relative_parts)

    def _view_adapter(self, view: object) -> str:
        if isinstance(view, dict):
            return str(view.get("adapter", "plain_markdown"))
        return str(getattr(view, "adapter", "plain_markdown"))

    def _view_mode(self, view: object) -> str:
        if isinstance(view, dict):
            return str(view.get("mode", "read_write"))
        return str(getattr(view, "mode", "read_write"))

    def _view_allows_pull(self, view: object) -> bool:
        return self._view_mode(view) in {"read_only", "read_write"}

    def _view_allows_push(self, view: object) -> bool:
        return self._view_mode(view) == "read_write"
