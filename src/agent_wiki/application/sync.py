from pathlib import Path

from pydantic import BaseModel

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.adapters.obsidian import ObsidianAdapter
from agent_wiki.infrastructure.adapters.plain_markdown import PlainMarkdownAdapter
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository


class SyncInput(BaseModel):
    mode: str


class SyncResult(BaseModel):
    mode: str
    changed_files: list[str]


_ADAPTERS = {
    "plain_markdown": PlainMarkdownAdapter,
    "obsidian": ObsidianAdapter,
}


class SyncService:
    def execute(self, wiki: WikiConfig, actor: ResolvedActor, data: SyncInput) -> SyncResult:
        if data.mode == "status":
            self._check_permission(actor, wiki, "query")
            return self._status(wiki)
        if data.mode == "pull-view":
            self._check_permission(actor, wiki, "capture_raw")
            return self._pull_view(wiki, actor)
        if data.mode == "push-view":
            self._check_permission(actor, wiki, "capture_raw")
            return self._push_view(wiki)
        raise ValueError(f"unsupported sync mode: {data.mode}")

    def _check_permission(self, actor: ResolvedActor, wiki: WikiConfig, operation: str) -> None:
        decision = PermissionService().check(actor, operation, wiki, "raw")
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
        for view in wiki.external_views:
            if not self._view_allows_pull(view):
                continue
            adapter = self._get_adapter(view)
            external_path = Path(self._view_path(view))
            for source in external_path.glob("*.md"):
                document = adapter.read(str(source))
                target = pages_root / source.name
                target.write_text(document["content"], encoding="utf-8")
                changed_files.append(str(target.relative_to(wiki_root)))
                doc_id = source.stem
                pending.append_pending_manifest({
                    "doc_id": doc_id,
                    "page_type": "raw",
                    "source": "external_sync",
                    "last_writer": actor.actor_id,
                })
        return SyncResult(mode="pull-view", changed_files=changed_files)

    def _push_view(self, wiki: WikiConfig) -> SyncResult:
        wiki_root = Path(wiki.workspace_path)
        changed_files: list[str] = []
        for view in wiki.external_views:
            if not self._view_allows_push(view):
                continue
            adapter = self._get_adapter(view)
            external_path = Path(self._view_path(view))
            external_path.mkdir(exist_ok=True)
            for source in (wiki_root / "pages").glob("*.md"):
                target = external_path / source.name
                document: dict = {"content": source.read_text(encoding="utf-8")}
                if target.exists():
                    existing = adapter.read(str(target))
                    adapter_metadata = existing.get("adapter_metadata", {})
                    document["adapter_metadata"] = adapter_metadata
                adapter.write(str(target), document)
                changed_files.append(str(target))
        return SyncResult(mode="push-view", changed_files=changed_files)

    def _get_adapter(self, view: object) -> object:
        adapter_name = self._view_adapter(view)
        cls = _ADAPTERS.get(adapter_name, PlainMarkdownAdapter)
        return cls()

    def _view_path(self, view: object) -> str:
        if isinstance(view, dict):
            return str(view["path"])
        return str(view.path)

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
