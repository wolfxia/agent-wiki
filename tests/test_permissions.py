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
