from pathlib import Path
from shutil import copy2

from pydantic import BaseModel

from agent_wiki.bootstrap.registry_loader import WikiConfig


class SyncInput(BaseModel):
    mode: str


class SyncResult(BaseModel):
    mode: str
    changed_files: list[str]


class SyncService:
    def execute(self, wiki: WikiConfig, data: SyncInput) -> SyncResult:
        if data.mode == "status":
            return self._status(wiki)
        if data.mode == "pull-view":
            return self._pull_view(wiki)
        if data.mode == "push-view":
            return self._push_view(wiki)
        raise ValueError(f"unsupported sync mode: {data.mode}")

    def _status(self, wiki: WikiConfig) -> SyncResult:
        wiki_root = Path(wiki.workspace_path)
        changed_files = [str(path.relative_to(wiki_root)) for path in (wiki_root / "pages").glob("*.md")]
        return SyncResult(mode="status", changed_files=changed_files)

    def _pull_view(self, wiki: WikiConfig) -> SyncResult:
        wiki_root = Path(wiki.workspace_path)
        pages_root = wiki_root / "pages"
        pages_root.mkdir(exist_ok=True)
        changed_files: list[str] = []
        for view in wiki.external_views:
            external_path = Path(self._view_path(view))
            for source in external_path.glob("*.md"):
                target = pages_root / source.name
                copy2(source, target)
                changed_files.append(str(target.relative_to(wiki_root)))
        return SyncResult(mode="pull-view", changed_files=changed_files)

    def _push_view(self, wiki: WikiConfig) -> SyncResult:
        wiki_root = Path(wiki.workspace_path)
        changed_files: list[str] = []
        for view in wiki.external_views:
            external_path = Path(self._view_path(view))
            external_path.mkdir(exist_ok=True)
            for source in (wiki_root / "pages").glob("*.md"):
                target = external_path / source.name
                copy2(source, target)
                changed_files.append(str(target))
        return SyncResult(mode="push-view", changed_files=changed_files)

    def _view_path(self, view: object) -> str:
        if isinstance(view, dict):
            return str(view["path"])
        return str(view.path)
