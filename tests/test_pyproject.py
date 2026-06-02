from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


def test_dev_dependencies_include_httpx() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dev_dependencies = data["project"]["optional-dependencies"]["dev"]
    assert any(dep.startswith("httpx") for dep in dev_dependencies)


def test_runtime_dependencies_include_httpx() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = data["project"]["dependencies"]
    assert any(dep.startswith("httpx") for dep in dependencies)
