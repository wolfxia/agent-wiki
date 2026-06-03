from pathlib import Path

from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.identity.permissions import PermissionService


def test_permission_service_allows_matching_rule() -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    service = PermissionService()

    decision = service.check(
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        operation="capture_raw",
        wiki=wiki,
        page_type="raw",
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_permission_service_denies_non_matching_rule() -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    service = PermissionService()

    decision = service.check(
        ResolvedActor(actor_type="human", actor_id="chao", transport="cli"),
        operation="capture_raw",
        wiki=wiki,
        page_type="raw",
    )

    assert decision.allowed is False


def test_permission_service_enforces_max_gate() -> None:
    from agent_wiki.bootstrap.registry_loader import PermissionConfig

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    # Add a permission that allows promote_principle but with max_gate=B
    wiki = wiki.model_copy(
        update={
            "permissions": wiki.permissions + [
                PermissionConfig(
                    actor_type="agent",
                    actor_id="claude-code",
                    allowed_operations=["promote_principle"],
                    max_gate="B",
                    allowed_page_types=["principle"],
                )
            ]
        }
    )
    service = PermissionService()

    decision = service.check(
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        operation="promote_principle",
        wiki=wiki,
        page_type="principle",
    )

    assert decision.allowed is False
    assert "gate" in decision.reason.lower()


def test_permission_decision_includes_required_gate() -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    service = PermissionService()

    decision = service.check(
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        operation="capture_raw",
        wiki=wiki,
        page_type="raw",
    )

    assert decision.allowed is True
    assert decision.required_gate == "A"



def test_permission_config_and_gate_service_accept_operation_enum() -> None:
    from agent_wiki.bootstrap.registry_loader import PermissionConfig
    from agent_wiki.domain.enums import Operation, PageType
    from agent_wiki.infrastructure.identity.gates import GateService

    permission = PermissionConfig(
        actor_type="agent",
        actor_id="claude-code",
        allowed_operations=[Operation.CAPTURE_RAW, Operation.QUERY],
        max_gate="B",
        allowed_page_types=[PageType.RAW],
    )

    assert permission.allowed_operations[0] == Operation.CAPTURE_RAW
    assert GateService().required_gate(Operation.CAPTURE_RAW, PageType.RAW) == "A"


def test_permission_service_reports_required_gate_for_sync() -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    service = PermissionService()

    decision = service.check(
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        operation="sync",
        wiki=wiki,
        page_type="raw",
    )

    assert decision.allowed is True
    assert decision.required_gate == "A"


def test_permission_service_allows_phase1_shared_agent_profiles() -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    service = PermissionService()

    hermes = service.check(
        ResolvedActor(actor_type="agent", actor_id="hermes", transport="mcp"),
        operation="sync",
        wiki=wiki,
        page_type="raw",
    )
    claude = service.check(
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        operation="compile_update",
        wiki=wiki,
        page_type="atom",
    )
    codex = service.check(
        ResolvedActor(actor_type="agent", actor_id="codex", transport="cli"),
        operation="compile_update",
        wiki=wiki,
        page_type="atom",
    )

    assert hermes.allowed is True
    assert claude.allowed is True
    assert codex.allowed is False
    assert codex.reason == "no matching permission rule"
    assert codex.required_gate is None


def test_permission_service_allows_codex_test_self_evolution_operations() -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    service = PermissionService()

    compile_decision = service.check(
        ResolvedActor(actor_type="agent", actor_id="codex-test", transport="cli"),
        operation="compile_update",
        wiki=wiki,
        page_type="atom",
    )
    sync_decision = service.check(
        ResolvedActor(actor_type="agent", actor_id="codex-test", transport="cli"),
        operation="sync",
        wiki=wiki,
        page_type="raw",
    )
    lint_decision = service.check(
        ResolvedActor(actor_type="agent", actor_id="codex-test", transport="cli"),
        operation="lint",
        wiki=wiki,
        page_type="raw",
    )

    assert compile_decision.allowed is True
    assert compile_decision.required_gate == "B"
    assert sync_decision.allowed is True
    assert sync_decision.required_gate == "A"
    assert lint_decision.allowed is True
    assert lint_decision.required_gate == "A"


def test_permission_service_denies_codex_test_c_gate_operations() -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    service = PermissionService()

    decision = service.check(
        ResolvedActor(actor_type="agent", actor_id="codex-test", transport="cli"),
        operation="promote_principle",
        wiki=wiki,
        page_type="principle",
    )

    assert decision.allowed is False
    assert decision.reason == "no matching permission rule"
    assert decision.required_gate is None
