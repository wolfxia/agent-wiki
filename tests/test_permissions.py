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
