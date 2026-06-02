from __future__ import annotations
from pathlib import Path

from agent_wiki.application.propagation import PropagationService
from agent_wiki.bootstrap.registry_loader import RegistryLoader, WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CompileAnalysis, CompileResult, CompileUpdateInput
from agent_wiki.domain.validators import validate_doc_id
from agent_wiki.extensions.page_types import get_page_type_registry, normalize_page_type
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository
from agent_wiki.settings import DEFAULT_REGISTRY_PATH


class CompileUpdateService:
    def __init__(self, registry_path: Path | None = None) -> None:
        self._registry_path = registry_path or DEFAULT_REGISTRY_PATH

    def analyze(self, wiki: WikiConfig, actor: ResolvedActor, data: CompileUpdateInput) -> CompileAnalysis:
        manifest = ManifestRepository(Path(wiki.workspace_path))
        existing = manifest.find(data.doc_id)
        if existing is not None:
            return CompileAnalysis(target_doc_id=data.doc_id, change_type="revise", gate="B")

        for entry in manifest.read_all():
            if entry.get("page_type") == data.page_type and entry.get("problem_cluster") == data.problem_cluster:
                return CompileAnalysis(target_doc_id=entry["doc_id"], change_type="revise", gate="B")

        return CompileAnalysis(target_doc_id=data.doc_id, change_type="create", gate="B")

    def apply(self, wiki: WikiConfig, actor: ResolvedActor, data: CompileUpdateInput) -> CompileResult:
        manifest = ManifestRepository(Path(wiki.workspace_path))
        validate_doc_id(data.doc_id)
        page_type = normalize_page_type(data.page_type)
        page_type_definition = get_page_type_registry().get(page_type)
        if page_type not in wiki.allowed_page_types:
            raise ValueError(f"page type {page_type} is not allowed")

        permission_service = PermissionService()
        decision = permission_service.check(actor, "compile_update", wiki, page_type)
        if not decision.allowed:
            raise PermissionError(decision.reason)

        if page_type_definition.requires_source_refs and not data.allow_shared_write_without_sources and not self._source_refs_are_valid(wiki, manifest, data.source_refs):
            raise ValueError("source_refs must point to existing raw pages")

        propagation = PropagationService(Path(wiki.workspace_path))
        data = data.model_copy(update={"page_type": page_type})
        return propagation.propagate_compile_update(wiki=wiki, actor=actor, data=data)

    def _source_refs_are_valid(self, wiki: WikiConfig, manifest: ManifestRepository, source_refs: list[str]) -> bool:
        if not source_refs:
            return False
        for source_ref in source_refs:
            try:
                wiki_id, doc_id = source_ref.split(":", maxsplit=1)
            except ValueError:
                return False
            target_manifest = manifest if wiki_id == wiki.wiki_id else self._manifest_for_wiki_id(wiki_id)
            if target_manifest is None:
                return False
            entry = target_manifest.find(doc_id)
            if entry is None or entry.get("page_type") != "raw":
                return False
        return True

    def _manifest_for_wiki_id(self, wiki_id: str) -> ManifestRepository | None:
        if not self._registry_path.exists():
            return None
        registry = RegistryLoader().load(self._registry_path)
        target = next((candidate for candidate in registry.wikis if candidate.wiki_id == wiki_id), None)
        if target is None:
            return None
        return ManifestRepository(Path(target.workspace_path))
