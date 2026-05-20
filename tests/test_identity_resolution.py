from agent_wiki.domain.models import IdentityContext
from agent_wiki.infrastructure.identity.resolver import IdentityResolver


def test_identity_resolver_uses_trusted_metadata_for_mcp() -> None:
    resolver = IdentityResolver()

    actor = resolver.resolve(
        IdentityContext(
            transport="mcp",
            actor_type="agent",
            actor_id="spoofed",
            metadata={"actor_type": "agent", "actor_id": "hermes"},
        )
    )

    assert actor.actor_type == "agent"
    assert actor.actor_id == "hermes"
    assert actor.transport == "mcp"


def test_identity_resolver_uses_trusted_metadata_for_rest() -> None:
    resolver = IdentityResolver()

    actor = resolver.resolve(
        IdentityContext(
            transport="rest",
            actor_type="agent",
            actor_id="spoofed",
            metadata={"actor_type": "service", "actor_id": "aw-agent"},
        )
    )

    assert actor.actor_type == "service"
    assert actor.actor_id == "aw-agent"
    assert actor.transport == "rest"


def test_identity_resolver_uses_explicit_cli_identity_when_metadata_present() -> None:
    resolver = IdentityResolver()

    actor = resolver.resolve(
        IdentityContext(
            transport="cli",
            actor_type="agent",
            actor_id="claude-code",
            metadata={"actor_type": "service", "actor_id": "aw-agent"},
        )
    )

    assert actor.actor_type == "agent"
    assert actor.actor_id == "claude-code"
    assert actor.transport == "cli"


def test_identity_resolver_uses_explicit_cli_identity_when_metadata_missing() -> None:
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


def test_identity_resolver_falls_back_to_metadata_when_cli_explicit_identity_missing() -> None:
    resolver = IdentityResolver()

    actor = resolver.resolve(
        IdentityContext(
            transport="cli",
            metadata={"actor_type": "service", "actor_id": "aw-agent"},
        )
    )

    assert actor.actor_type == "service"
    assert actor.actor_id == "aw-agent"


def test_identity_resolver_raises_when_identity_missing(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WIKI_ACTOR_TYPE", raising=False)
    monkeypatch.delenv("AGENT_WIKI_ACTOR_ID", raising=False)
    resolver = IdentityResolver()

    try:
        resolver.resolve(IdentityContext(transport="cli"))
    except Exception as error:
        assert error.__class__.__name__ == "IdentityResolutionError"
    else:
        raise AssertionError("expected IdentityResolutionError")


def test_identity_resolver_prefers_explicit_identity_over_env(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WIKI_ACTOR_TYPE", "agent")
    monkeypatch.setenv("AGENT_WIKI_ACTOR_ID", "hermes")
    resolver = IdentityResolver(default_actor_type="agent", default_actor_id="openclaw")

    actor = resolver.resolve(
        IdentityContext(
            transport="cli",
            actor_type="agent",
            actor_id="claude-code",
        )
    )

    assert actor.actor_type == "agent"
    assert actor.actor_id == "claude-code"


def test_identity_resolver_uses_env_before_constructor_default(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WIKI_ACTOR_TYPE", "agent")
    monkeypatch.setenv("AGENT_WIKI_ACTOR_ID", "hermes")
    resolver = IdentityResolver(default_actor_type="agent", default_actor_id="openclaw")

    actor = resolver.resolve(IdentityContext(transport="mcp"))

    assert actor.actor_type == "agent"
    assert actor.actor_id == "hermes"


def test_identity_resolver_uses_constructor_default_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_WIKI_ACTOR_TYPE", raising=False)
    monkeypatch.delenv("AGENT_WIKI_ACTOR_ID", raising=False)
    resolver = IdentityResolver(default_actor_type="agent", default_actor_id="hermes")

    actor = resolver.resolve(IdentityContext(transport="mcp"))

    assert actor.actor_type == "agent"
    assert actor.actor_id == "hermes"
