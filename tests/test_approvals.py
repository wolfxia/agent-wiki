import json
from pathlib import Path

from agent_wiki.application.approvals import ApprovalService, ProposalInput
from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_principle_promotion_requires_proposal_and_approval(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml")).wikis[1].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    approval_service = ApprovalService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    proposal = approval_service.propose(
        wiki=wiki,
        actor=actor,
        data=ProposalInput(
            proposal_id="proposal-1",
            doc_id="principle-1",
            page_type="principle",
            topic="testing",
            problem_cluster="cluster-p1",
            content="# Principle one\n\nPromoted from synthesis.",
            source_refs=["personal-1:raw-source-approval"],
        ),
    )

    assert proposal.status == "proposed"
    proposal_path = temp_wiki_root / ".agent-wiki" / "proposals" / "proposal-1.json"
    assert proposal_path.exists()

    result = approval_service.approve(wiki=wiki, actor=actor, proposal_id="proposal-1")

    assert result.status == "approved"
    assert (temp_wiki_root / "pages" / "principle-1.md").exists()
    log_entry = json.loads((temp_wiki_root / "approval_log.jsonl").read_text().strip())
    assert log_entry["proposal_id"] == "proposal-1"



def test_proposal_rejects_path_traversal_proposal_id(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml")).wikis[1].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    approval_service = ApprovalService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    try:
        approval_service.propose(
            wiki=wiki,
            actor=actor,
            data=ProposalInput(
                proposal_id="../escape",
                doc_id="principle-safe",
                page_type="principle",
                topic="testing",
                problem_cluster="cluster-p1",
                content="# Principle safe",
                source_refs=["personal-1:raw-source-approval"],
            ),
        )
    except ValueError as error:
        assert "proposal_id" in str(error)
    else:
        raise AssertionError("expected proposal_id validation failure")


def test_approve_rejects_path_traversal_proposal_lookup(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml")).wikis[1].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    approval_service = ApprovalService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    try:
        approval_service.approve(wiki=wiki, actor=actor, proposal_id="../escape")
    except ValueError as error:
        assert "proposal_id" in str(error)
    else:
        raise AssertionError("expected proposal_id validation failure")
