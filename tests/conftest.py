from pathlib import Path
from shutil import copytree

import pytest

from agent_wiki.bootstrap.container import Container


@pytest.fixture()
def container() -> Container:
    return Container()


@pytest.fixture()
def registry_path() -> Path:
    return Path("tests/fixtures/registry.yaml")


@pytest.fixture()
def temp_wiki_root(tmp_path: Path) -> Path:
    source = Path("tests/fixtures/sample_wiki")
    target = tmp_path / "sample_wiki"
    copytree(source, target)
    return target
