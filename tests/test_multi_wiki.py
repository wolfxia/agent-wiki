from pathlib import Path
from shutil import copytree

from agent_wiki.bootstrap.registry_loader import RegistryLoader


def test_multi_wiki_registry_loads_personal_and_shared_wikis(tmp_path: Path) -> None:
    personal_target = tmp_path / "sample_wiki"
    shared_target = tmp_path / "shared_wiki"
    copytree(Path("tests/fixtures/sample_wiki"), personal_target)
    copytree(Path("tests/fixtures/shared_wiki"), shared_target)

    registry = RegistryLoader().load(Path("tests/fixtures/registry_multi.yaml"))
    registry = registry.model_copy(
        update={
            "wikis": [
                registry.wikis[0].model_copy(update={"workspace_path": str(personal_target)}),
                registry.wikis[1].model_copy(update={"workspace_path": str(shared_target)}),
            ]
        }
    )

    assert len(registry.wikis) == 2
    assert registry.wikis[0].wiki_id == "personal-1"
    assert registry.wikis[1].wiki_id == "shared-1"
