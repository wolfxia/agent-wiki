from __future__ import annotations
import json
from pathlib import Path

from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.propagation import PropagationService
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import ApprovalResult, CompileUpdateInput, ProposalInput, ProposalResult
from agent_wiki.domain.validators import validate_doc_id, validate_proposal_id
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository
from agent_wiki.settings import DEFAULT_REGISTRY_PATH


class ApprovalService:
    def __init__(self, registry_path: Path | None = None) -> None:
        self._registry_path = registry_path or DEFAULT_REGISTRY_PATH

    def propose(self, wiki: WikiConfig, actor: ResolvedActor, data: ProposalInput) -> ProposalResult:
        validate_proposal_id(data.proposal_id)
        validate_doc_id(data.doc_id)
        runtime_root = Path(wiki.workspace_path) / ".agent-wiki" / "proposals"
        runtime_root.mkdir(parents=True, exist_ok=True)
        proposal_path = runtime_root / f"{data.proposal_id}.json"
        proposal_path.write_text(
            json.dumps(
                {
                    "proposal_id": data.proposal_id,
                    "doc_id": data.doc_id,
                    "page_type": data.page_type,
                    "topic": data.topic,
                    "problem_cluster": data.problem_cluster,
                    "content": data.content,
                    "source_refs": data.source_refs,
                    "actor_id": actor.actor_id,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return ProposalResult(status="proposed", proposal_id=data.proposal_id)

    def approve(self, wiki: WikiConfig, actor: ResolvedActor, proposal_id: str) -> ApprovalResult:
        validate_proposal_id(proposal_id)
        proposal_path = Path(wiki.workspace_path) / ".agent-wiki" / "proposals" / f"{proposal_id}.json"
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

        decision = PermissionService().check(actor, "approve_proposal", wiki, proposal["page_type"])
        if not decision.allowed:
            raise PermissionError(decision.reason)

        validate_doc_id(proposal["doc_id"])
        if proposal["page_type"] not in wiki.allowed_page_types:
            raise ValueError(f"page type {proposal['page_type']} is not allowed")

        compile_service = CompileUpdateService(registry_path=self._registry_path)
        manifest = ManifestRepository(Path(wiki.workspace_path))
        if not compile_service._source_refs_are_valid(wiki, manifest, proposal["source_refs"]):
            raise ValueError("source_refs must point to existing raw pages")

        propagation = PropagationService(Path(wiki.workspace_path))
        result = propagation.propagate_compile_update(
            wiki=wiki,
            actor=actor,
            data=CompileUpdateInput(
                doc_id=proposal["doc_id"],
                page_type=proposal["page_type"],
                topic=proposal["topic"],
                problem_cluster=proposal["problem_cluster"],
                content=proposal["content"],
                source_refs=proposal["source_refs"],
            ),
        )
        approval_log_path = Path(wiki.workspace_path) / "approval_log.jsonl"
        with approval_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"proposal_id": proposal_id, "doc_id": proposal["doc_id"]}, ensure_ascii=False) + "\n")
        return ApprovalResult(status="approved", doc_id=result.doc_id)
