import json
from pathlib import Path
from shutil import copytree

import yaml

from agent_wiki.application.approvals import ApprovalService, ProposalInput
from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_principle_promotion_requires_proposal_and_approval(temp_wiki_root: Path, tmp_path: Path) -> None:
    personal_root = tmp_path / "approval-personal-wiki"
    shared_root = tmp_path / "approval-shared-wiki"
    copytree(Path("tests/fixtures/sample_wiki"), personal_root)
    copytree(Path("tests/fixtures/shared_wiki"), shared_root)

    registry_path = tmp_path / "registry-multi.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry_multi.yaml").read_text())
    registry_data["wikis"][0]["workspace_path"] = str(personal_root)
    registry_data["wikis"][1]["workspace_path"] = str(shared_root)
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    personal = RegistryLoader().load(registry_path).wikis[0]
    wiki = RegistryLoader().load(registry_path).wikis[1]
    CaptureRawService().execute(
        wiki=personal,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-source-approval",
            topic="testing",
            problem_cluster="cluster-p1",
            content="# Raw source approval",
            source_refs=[],
        ),
    )
    approval_service = ApprovalService(registry_path=registry_path)
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
    proposal_path = shared_root / ".agent-wiki" / "proposals" / "proposal-1.json"
    assert proposal_path.exists()

    result = approval_service.approve(wiki=wiki, actor=actor, proposal_id="proposal-1")

    assert result.status == "approved"
    assert (shared_root / "pages" / "principle-1.md").exists()
    log_entry = json.loads((shared_root / "approval_log.jsonl").read_text().strip())
    assert log_entry["proposal_id"] == "proposal-1"



def test_proposal_rejects_path_traversal_proposal_id(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml")).wikis[1].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    approval_service = ApprovalService(registry_path=Path("tests/fixtures/registry_multi.yaml"))
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
    approval_service = ApprovalService(registry_path=Path("tests/fixtures/registry_multi.yaml"))
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    try:
        approval_service.approve(wiki=wiki, actor=actor, proposal_id="../escape")
    except ValueError as error:
        assert "proposal_id" in str(error)
    else:
        raise AssertionError("expected proposal_id validation failure")



def test_approval_rejects_missing_or_non_raw_source_refs(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml")).wikis[1].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    approval_service = ApprovalService(registry_path=Path("tests/fixtures/registry_multi.yaml"))
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")

    approval_service.propose(
        wiki=wiki,
        actor=actor,
        data=ProposalInput(
            proposal_id="proposal-invalid-sources",
            doc_id="principle-invalid-sources",
            page_type="principle",
            topic="testing",
            problem_cluster="cluster-p1",
            content="# Principle invalid sources",
            source_refs=["personal-1:missing-raw"],
        ),
    )

    try:
        approval_service.approve(wiki=wiki, actor=actor, proposal_id="proposal-invalid-sources")
    except ValueError as error:
        assert "source_refs" in str(error)
    else:
        raise AssertionError("expected source_refs validation failure")


def test_approval_enforces_permission_for_approve_proposal(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml")).wikis[1].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    approval_service = ApprovalService(registry_path=Path("tests/fixtures/registry_multi.yaml"))
    proposer = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    approver = ResolvedActor(actor_type="agent", actor_id="codex", transport="mcp")

    approval_service.propose(
        wiki=wiki,
        actor=proposer,
        data=ProposalInput(
            proposal_id="proposal-low-gate",
            doc_id="principle-low-gate",
            page_type="principle",
            topic="testing",
            problem_cluster="cluster-p1",
            content="# Principle low gate",
            source_refs=["personal-1:raw-source-approval"],
        ),
    )

    try:
        approval_service.approve(wiki=wiki, actor=approver, proposal_id="proposal-low-gate")
    except PermissionError as error:
        assert "permission" in str(error).lower() or "no matching" in str(error).lower() or "gate" in str(error).lower()
    else:
        raise AssertionError("expected approval permission failure")
