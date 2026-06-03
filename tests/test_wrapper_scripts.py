import os
from pathlib import Path
import subprocess


def test_runtime_repositories_share_file_lock_implementation() -> None:
    import agent_wiki.infrastructure.runtime.file_lock as file_lock

    assert hasattr(file_lock, "FileLock")
    for path in (
        Path("src/agent_wiki/infrastructure/runtime/claim_annotations.py"),
        Path("src/agent_wiki/infrastructure/runtime/review_queue.py"),
        Path("src/agent_wiki/infrastructure/retrieval/topic_index.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "from agent_wiki.infrastructure.runtime.file_lock import FileLock" in source
        assert "class _FileLock" not in source


def test_dream_cycle_wrapper_uses_portable_grep_extended_regex() -> None:
    source = Path("scripts/aw-dream-cycle.sh").read_text(encoding="utf-8")

    assert "grep -oP" not in source
    assert "grep -oE 'orphan_count=[0-9]+'" in source
    assert "grep -oE 'candidate_group_count=[0-9]+'" in source
    assert "grep -oE 'synthesis_count=[0-9]+'" in source


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
