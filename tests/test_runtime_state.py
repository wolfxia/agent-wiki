from pathlib import Path

from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository


def test_pending_state_writes_and_reads_stale_markers(temp_wiki_root: Path) -> None:
    repo = PendingStateRepository(temp_wiki_root)
    repo.append_stale_marker({
        "doc_id": "atom-stale-1",
        "reason": "downstream propagation failed",
        "actor_id": "claude-code",
    })
    repo.append_stale_marker({
        "doc_id": "atom-stale-2",
        "reason": "gate failed",
        "actor_id": "claude-code",
    })

    markers = repo.read_stale_markers()
    assert len(markers) == 2
    assert markers[0]["doc_id"] == "atom-stale-1"
    assert markers[1]["reason"] == "gate failed"


def test_pending_state_returns_empty_when_no_stale_file(temp_wiki_root: Path) -> None:
    repo = PendingStateRepository(temp_wiki_root)
    assert repo.read_stale_markers() == []
