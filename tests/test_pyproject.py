from pathlib import Path

import tomllib


def test_dev_dependencies_include_httpx() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dev_dependencies = data["project"]["optional-dependencies"]["dev"]
    assert any(dep.startswith("httpx") for dep in dev_dependencies)


def test_runtime_dependencies_include_httpx() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = data["project"]["dependencies"]
    assert any(dep.startswith("httpx") for dep in dependencies)
