from __future__ import annotations
import json
from pathlib import Path
from time import time

from pydantic import BaseModel

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.adapters.obsidian import ObsidianAdapter
from agent_wiki.infrastructure.doc_id import doc_id_from_relative_path
from agent_wiki.infrastructure.adapters.plain_markdown import PlainMarkdownAdapter
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.intake.raw_intake import normalize_raw_intake
from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository
from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository
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
        run_started_at = time()
        last_sync_time = self._read_pull_view_last_sync_time(wiki_root)
        pending = PendingStateRepository(wiki_root)
        manifest = ManifestRepository(wiki_root)
        retrieval_index = RetrievalIndexRepository(wiki_root)
        fts_index = SQLiteFTSIndexProvider(wiki_root, wiki_id=wiki.wiki_id)
        topic_index = TopicIndexRepository(wiki_root)
        changed_files: list[str] = []
        manifest_changes: list[dict] = []
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
                if last_sync_time is not None and source.stat().st_mtime <= last_sync_time:
                    continue
                vault_relative_path = str(source.relative_to(external_path))
                doc_id = self._doc_id_for_pull_view_source(source, external_path)
                target = pages_root / f"{doc_id}.md"
                if target in seen_targets:
                    continue
                document = adapter.read(str(source))
                target.write_text(document["content"], encoding="utf-8")
                changed_files.append(str(target.relative_to(wiki_root)))
                seen_targets.add(target)
                frontmatter = document.get("adapter_metadata", {}).get("frontmatter", {})
                intake = normalize_raw_intake(
                    {
                        "doc_id": doc_id,
                        "topic": frontmatter.get("topic") or source.parent.name,
                        "problem_cluster": frontmatter.get("problem_cluster") or source.parent.name,
                        "summary": frontmatter.get("summary"),
                        "classification_confidence": frontmatter.get("classification_confidence"),
                        "content": document["content"],
                        "source_type": "external_sync",
                        "source_uri": vault_relative_path,
                        "adapter_metadata": {
                            **document.get("adapter_metadata", {}),
                            "vault_relative_path": vault_relative_path,
                        },
                        "frontmatter": frontmatter,
                    }
                )
                retrieval_index.append_raw_card(
                    wiki.wiki_id,
                    type("PullViewRawCard", (), {
                        "doc_id": doc_id,
                        "topic": intake["topic"],
                        "problem_cluster": intake["problem_cluster"],
                        "content": document["content"],
                    })(),
                )
                fts_index.upsert(doc_id, {
                    "wiki_id": wiki.wiki_id,
                    "doc_id": doc_id,
                    "page_type": "raw",
                    "topic": intake["topic"],
                    "problem_cluster": intake["problem_cluster"],
                    "summary": intake["summary"],
                    "content": document["content"],
                })
                manifest_changes.append(
                    {
                        "wiki_id": wiki.wiki_id,
                        "doc_id": doc_id,
                        "page_type": "raw",
                        "topic": intake["topic"],
                        "problem_cluster": intake["problem_cluster"],
                        "summary": intake["summary"],
                        "classification_method": intake["classification_method"],
                        "classification_confidence": intake["classification_confidence"],
                        "metadata_state": intake["metadata_state"],
                        "source_type": intake["source_type"],
                        "source_uri": intake["source_uri"],
                        "title": intake["title"],
                        "canonical_uri": f"pages/{doc_id}.md",
                        "last_writer": actor.actor_id,
                        "source": "external_sync",
                        "vault_relative_path": vault_relative_path,
                        "adapter_metadata": intake["adapter_metadata"],
                    }
                )
                topic_index.upsert({
                    "doc_id": doc_id,
                    "page_type": "raw",
                    "topic": intake["topic"],
                    "problem_cluster": intake["problem_cluster"],
                    "summary": intake["summary"],
                })
                pending.append_pending_manifest({
                    "doc_id": doc_id,
                    "page_type": "raw",
                    "source": "external_sync",
                    "last_writer": actor.actor_id,
                    "vault_relative_path": vault_relative_path,
                    "adapter_metadata": intake["adapter_metadata"],
                })
        manifest.batch_upsert(manifest_changes)
        self._write_pull_view_last_sync_time(wiki_root, run_started_at)
        return SyncResult(mode="pull-view", changed_files=changed_files)

    def _read_pull_view_last_sync_time(self, wiki_root: Path) -> float | None:
        state_path = self._pull_view_state_path(wiki_root)
        if not state_path.exists():
            return None
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        value = data.get("last_sync_time")
        if isinstance(value, int | float):
            return float(value)
        return None

    def _write_pull_view_last_sync_time(self, wiki_root: Path, last_sync_time: float) -> None:
        state_path = self._pull_view_state_path(wiki_root)
        state_path.parent.mkdir(exist_ok=True)
        state_path.write_text(
            json.dumps({"last_sync_time": last_sync_time}, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def _pull_view_state_path(self, wiki_root: Path) -> Path:
        return wiki_root / ".agent-wiki" / "pull_view_state.json"

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
            is_obsidian = self._view_adapter(view) == "obsidian"
            routing = self._view_push_view_routing(view) if is_obsidian else {}
            for source in self._iter_export_sources(wiki_root, doc_ids):
                target = self._resolve_export_target(
                    external_path,
                    source,
                    manifest,
                    is_obsidian=is_obsidian,
                    routing=routing,
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                document: dict = {"content": source.read_text(encoding="utf-8")}
                if target.exists():
                    existing = adapter.read(str(target))
                    adapter_metadata = existing.get("adapter_metadata", {})
                    document["adapter_metadata"] = adapter_metadata
                adapter.write(str(target), document)
                changed_files.append(str(target))

            if self._view_adapter(view) == "obsidian":
                changed_files.append(self._write_obsidian_graph_index(wiki, external_path, routing))

        return SyncResult(mode="push-view", changed_files=changed_files)

    def _write_obsidian_graph_index(self, wiki: WikiConfig, external_path: Path, routing: dict) -> str:
        manifest_entries = ManifestRepository(Path(wiki.workspace_path)).read_all()
        index_folder = routing.get("graph_index_folder", "knowledge-graph")
        index_title = routing.get("graph_index_title", "Knowledge Graph Index")
        index_path = external_path / index_folder / "index.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        content = ObsidianAdapter().render_graph_index(manifest_entries, title=index_title)
        index_path.write_text(content, encoding="utf-8")
        return str(index_path)

    def _iter_export_sources(self, wiki_root: Path, doc_ids: list[str] | None) -> list[Path]:
        pages_root = wiki_root / "pages"
        manifest = ManifestRepository(wiki_root)
        if doc_ids:
            sources: list[Path] = []
            for doc_id in doc_ids:
                entry = manifest.find(doc_id)
                if entry and entry.get("canonical_uri"):
                    source = wiki_root / str(entry["canonical_uri"])
                else:
                    source = pages_root / f"{doc_id}.md"
                if source.exists():
                    sources.append(source)
            return sources

        manifest_sources = []
        for entry in manifest.read_all():
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                continue
            source = wiki_root / str(canonical_uri)
            if source.exists() and source.is_file():
                manifest_sources.append(source)
        if manifest_sources:
            return sorted(manifest_sources)
        return sorted(pages_root.rglob("*.md"))

    def _resolve_export_target(
        self,
        external_root: Path,
        source: Path,
        manifest: ManifestRepository,
        *,
        is_obsidian: bool = False,
        routing: dict | None = None,
    ) -> Path:
        entry = self._manifest_entry_for_source(source, manifest)
        if entry is not None:
            relative_path = entry.get("vault_relative_path")
            if relative_path:
                return external_root / relative_path
            if is_obsidian:
                return external_root / self._default_obsidian_relative_path(entry, source.name, routing=routing)
        return external_root / source.name

    def _manifest_entry_for_source(self, source: Path, manifest: ManifestRepository) -> dict | None:
        entry = manifest.find(source.stem)
        if entry is not None:
            return entry
        for candidate in manifest.read_all():
            if candidate.get("canonical_uri") and Path(str(candidate["canonical_uri"])).name == source.name:
                return candidate
        return None

    def _view_push_view_routing(self, view: object) -> dict:
        if isinstance(view, dict):
            return dict(view.get("push_view_routing") or {})
        value = getattr(view, "push_view_routing", None)
        if value is None:
            return {}
        if hasattr(value, "model_dump"):
            return value.model_dump()
        return dict(value)

    def _default_obsidian_relative_path(self, entry: dict, filename: str, routing: dict | None = None) -> Path:
        routing = routing or {}
        page_type = str(entry.get("page_type") or "").strip()
        topic = str(entry.get("topic") or "").strip()
        cluster = str(entry.get("problem_cluster") or "").strip()
        direction_folders = dict(routing.get("direction_folders") or {})
        fallback_folders = dict(routing.get("fallback_folders") or {})
        direction = direction_folders.get(topic) or direction_folders.get(cluster)
        if direction:
            return Path(direction) / filename
        if page_type == "synthesis":
            base = fallback_folders.get("synthesis", "synthesis")
            return Path(base) / (cluster or "uncategorized") / filename
        if page_type == "atom":
            base = fallback_folders.get("atom", "atoms")
            return Path(base) / filename
        if page_type == "principle":
            base = fallback_folders.get("principle", "principles")
            return Path(base) / filename
        base = fallback_folders.get("raw", "raw")
        return Path(base) / filename

    def _rebuild_retrieval_index(self, wiki: WikiConfig) -> None:
        wiki_root = Path(wiki.workspace_path)
        pages_root = wiki_root / "pages"
        retrieval_index = RetrievalIndexRepository(wiki_root)
        retrieval_index.index_path.write_text("", encoding="utf-8")
        fts_index = SQLiteFTSIndexProvider(wiki_root, wiki_id=wiki.wiki_id)
        manifest = ManifestRepository(wiki_root)
        pending = PendingStateRepository(wiki_root)

        pending_entries: dict[str, dict] = {}
        pending_path = wiki_root / ".agent-wiki" / "pending_manifest.jsonl"
        if pending_path.exists():
            for line in pending_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = __import__("json").loads(line)
                pending_entries[entry.get("doc_id", "")] = entry

        for page_path in sorted(pages_root.glob("*.md")):
            doc_id = page_path.stem
            manifest_entry = manifest.find(doc_id) or pending_entries.get(doc_id) or {}
            content = page_path.read_text(encoding="utf-8")
            retrieval_index.append_raw_card(
                wiki.wiki_id,
                type("RebuiltRawCard", (), {
                    "doc_id": doc_id,
                    "topic": manifest_entry.get("topic", ""),
                    "problem_cluster": manifest_entry.get("problem_cluster", ""),
                    "content": content,
                })(),
            )
            fts_index.upsert(doc_id, {
                "wiki_id": wiki.wiki_id,
                "doc_id": doc_id,
                "page_type": manifest_entry.get("page_type", "raw"),
                "topic": manifest_entry.get("topic", ""),
                "problem_cluster": manifest_entry.get("problem_cluster", ""),
                "summary": manifest_entry.get("summary", ""),
                "content": content,
                "sensitivity": manifest_entry.get("sensitivity", ""),
            })


    def _doc_id_for_pull_view_source(self, source: Path, external_root: Path) -> str:
        relative_path = source.relative_to(external_root)
        if len(relative_path.parts) == 1:
            relative_path = Path(external_root.name) / relative_path
        return doc_id_from_relative_path(relative_path)

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
