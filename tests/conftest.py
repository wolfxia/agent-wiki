from pathlib import Path
from shutil import copytree, rmtree

import pytest

from agent_wiki.bootstrap.container import Container


_RUNTIME_FILES = (
    "MANIFEST.jsonl",
    "retrieval_index.jsonl",
    "query_outcomes.jsonl",
    "query_hits.jsonl",
    "log.md",
    "operation_log.jsonl",
    "review_queue.jsonl",
    "authority_log.jsonl",
    "approval_log.jsonl",
)


def _reset_runtime_artifacts(root: Path) -> None:
    for relative in _RUNTIME_FILES:
        candidate = root / relative
        if candidate.exists():
            candidate.unlink()

    pages_root = root / "pages"
    if pages_root.exists():
        for page in pages_root.glob("*.md"):
            page.unlink()

    runtime_root = root / ".agent-wiki"
    if runtime_root.exists():
        for child in runtime_root.iterdir():
            if child.is_dir():
                rmtree(child)
            else:
                child.unlink()


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
    _reset_runtime_artifacts(target)
    return target
