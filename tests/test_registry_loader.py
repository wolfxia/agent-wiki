from pathlib import Path

from agent_wiki.bootstrap.registry_loader import RegistryLoader


def test_registry_loader_reads_registry_fixture() -> None:
    loader = RegistryLoader()

    registry = loader.load(Path("tests/fixtures/registry.yaml"))

    assert registry.version == 1
    assert registry.default_route_policy == "purpose_then_topic"
    assert len(registry.wikis) == 1
    assert registry.wikis[0].wiki_id == "personal-1"
