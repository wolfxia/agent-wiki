from pathlib import Path


def test_dockerfile_runs_aw_serve_as_default_process() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim" in dockerfile
    assert "pip install --no-cache-dir ." in dockerfile
    assert 'CMD ["aw", "serve"]' in dockerfile or 'ENTRYPOINT ["aw", "serve"]' in dockerfile
