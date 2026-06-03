import os
from pathlib import Path
import subprocess


def test_aw_codex_test_wrapper_injects_codex_test_identity(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_aw = fake_bin / "aw"
    fake_aw.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$AGENT_WIKI_ACTOR_TYPE|$AGENT_WIKI_ACTOR_ID|$AGENT_WIKI_REGISTRY\"\n",
        encoding="utf-8",
    )
    fake_aw.chmod(0o755)

    result = subprocess.run(
        ["bash", "scripts/aw-codex-test", "query", "x"],
        cwd=Path.cwd(),
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "AW_VENV": str(tmp_path / "missing-venv"),
            "AW_REGISTRY": "/tmp/test-registry.yaml",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "agent|codex-test|/tmp/test-registry.yaml" in result.stdout
