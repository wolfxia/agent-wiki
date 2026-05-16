from agent_wiki.domain.models import IdentityContext
from agent_wiki.infrastructure.identity.resolver import IdentityResolver


def test_identity_resolver_prefers_metadata_over_explicit_values() -> None:
    resolver = IdentityResolver()

    actor = resolver.resolve(
        IdentityContext(
            transport="cli",
            actor_type="agent",
            actor_id="claude-code",
            metadata={"actor_type": "service", "actor_id": "aw-agent"},
        )
    )

    assert actor.actor_type == "service"
    assert actor.actor_id == "aw-agent"
    assert actor.transport == "cli"


def test_identity_resolver_falls_back_to_explicit_when_no_metadata() -> None:
    resolver = IdentityResolver()

    actor = resolver.resolve(
        IdentityContext(
            transport="cli",
            actor_type="agent",
            actor_id="claude-code",
        )
    )

    assert actor.actor_type == "agent"
    assert actor.actor_id == "claude-code"


def test_identity_resolver_falls_back_to_metadata() -> None:
    resolver = IdentityResolver()

    actor = resolver.resolve(
        IdentityContext(
            transport="mcp",
            metadata={"actor_type": "service", "actor_id": "aw-agent"},
        )
    )

    assert actor.actor_type == "service"
    assert actor.actor_id == "aw-agent"



def test_identity_resolver_raises_when_identity_missing() -> None:
    resolver = IdentityResolver()

    try:
        resolver.resolve(IdentityContext(transport="cli"))
    except Exception as error:
        assert error.__class__.__name__ == "IdentityResolutionError"
    else:
        raise AssertionError("expected IdentityResolutionError")
