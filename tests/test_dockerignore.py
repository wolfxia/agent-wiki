from pathlib import Path


def test_dockerignore_excludes_local_runtime_and_build_noise() -> None:
    dockerignore = Path(".dockerignore")
    assert dockerignore.exists()

    content = dockerignore.read_text(encoding="utf-8")
    assert ".venv" in content
    assert "__pycache__" in content
    assert "tests" in content
    assert "docs" in content
    assert ".agent-wiki" in content
