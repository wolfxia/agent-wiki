from pathlib import Path

from agent_wiki.application.propagation import PropagationService
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CompileAnalysis, CompileResult, CompileUpdateInput
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class CompileUpdateService:
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
        if data.page_type not in wiki.allowed_page_types:
            raise ValueError(f"page type {data.page_type} is not allowed")

        permission_service = PermissionService()
        decision = permission_service.check(actor, "compile_update", wiki, data.page_type)
        if not decision.allowed:
            raise PermissionError(decision.reason)

        if not data.allow_shared_write_without_sources and not self._source_refs_are_valid(wiki, manifest, data.source_refs):
            raise ValueError("source_refs must point to existing raw pages")

        if actor.actor_type == "agent" and data.page_type not in {"atom", "synthesis"}:
            raise ValueError("compile_update only supports atom and synthesis in Milestone 3")

        propagation = PropagationService(Path(wiki.workspace_path))
        return propagation.propagate_compile_update(wiki=wiki, actor=actor, data=data)

    def _source_refs_are_valid(self, wiki: WikiConfig, manifest: ManifestRepository, source_refs: list[str]) -> bool:
        if not source_refs:
            return False
        for source_ref in source_refs:
            try:
                wiki_id, doc_id = source_ref.split(":", maxsplit=1)
            except ValueError:
                return False
            if wiki_id != wiki.wiki_id:
                return False
            entry = manifest.find(doc_id)
            if entry is None or entry.get("page_type") != "raw":
                return False
        return True
