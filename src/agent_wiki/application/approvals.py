import json
from pathlib import Path

from agent_wiki.application.propagation import PropagationService
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import ApprovalResult, CompileUpdateInput, ProposalInput, ProposalResult


class ApprovalService:
    def propose(self, wiki: WikiConfig, actor: ResolvedActor, data: ProposalInput) -> ProposalResult:
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
        proposal_path = Path(wiki.workspace_path) / ".agent-wiki" / "proposals" / f"{proposal_id}.json"
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        propagation = PropagationService(Path(wiki.workspace_path))
        propagation.propagate_compile_update(
            wiki=wiki,
            actor=actor,
            data=CompileUpdateInput(
                doc_id=proposal["doc_id"],
                page_type=proposal["page_type"],
                topic=proposal["topic"],
                problem_cluster=proposal["problem_cluster"],
                content=proposal["content"],
                source_refs=proposal["source_refs"],
                allow_shared_write_without_sources=True,
            ),
        )
        approval_log_path = Path(wiki.workspace_path) / "approval_log.jsonl"
        with approval_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"proposal_id": proposal_id, "doc_id": proposal["doc_id"]}, ensure_ascii=False) + "\n")
        return ApprovalResult(status="approved", doc_id=proposal["doc_id"])
