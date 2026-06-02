from pathlib import Path
import logging

from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


def test_manifest_repository_appends_entry(temp_wiki_root: Path) -> None:
    repository = ManifestRepository(temp_wiki_root)

    repository.append(
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-1",
            "page_type": "raw",
            "canonical_uri": "pages/raw-1.md",
        }
    )

    manifest_path = temp_wiki_root / "MANIFEST.jsonl"
    assert manifest_path.exists()
    lines = manifest_path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert '"doc_id": "raw-1"' in lines[0]


def test_manifest_repository_rejects_duplicate_doc_id(temp_wiki_root: Path) -> None:
    repository = ManifestRepository(temp_wiki_root)
    entry = {
        "wiki_id": "personal-1",
        "doc_id": "raw-1",
        "page_type": "raw",
        "canonical_uri": "pages/raw-1.md",
    }

    repository.append(entry)

    try:
        repository.append(entry)
    except ValueError as error:
        assert "duplicate doc_id" in str(error)
    else:
        raise AssertionError("expected duplicate doc_id rejection")



def test_manifest_repository_deletes_entry_by_doc_id(temp_wiki_root: Path) -> None:
    repository = ManifestRepository(temp_wiki_root)
    repository.append({"wiki_id": "personal-1", "doc_id": "raw-1", "page_type": "raw", "canonical_uri": "pages/raw-1.md"})
    repository.append({"wiki_id": "personal-1", "doc_id": "raw-2", "page_type": "raw", "canonical_uri": "pages/raw-2.md"})

    assert repository.delete("raw-1") is True
    assert repository.find("raw-1") is None
    assert repository.find("raw-2") is not None
    assert repository.delete("raw-missing") is False


def test_manifest_repository_batch_upserts_entries(temp_wiki_root: Path) -> None:
    repository = ManifestRepository(temp_wiki_root)
    repository.append(
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-1",
            "page_type": "raw",
            "topic": "old",
            "canonical_uri": "pages/raw-1.md",
        }
    )

    repository.batch_upsert(
        [
            {
                "wiki_id": "personal-1",
                "doc_id": "raw-1",
                "page_type": "raw",
                "topic": "new",
                "canonical_uri": "pages/raw-1.md",
            },
            {
                "wiki_id": "personal-1",
                "doc_id": "raw-2",
                "page_type": "raw",
                "topic": "second",
                "canonical_uri": "pages/raw-2.md",
            },
        ]
    )

    assert repository.find("raw-1")["topic"] == "new"
    assert repository.find("raw-2")["topic"] == "second"
    assert len(repository.read_all()) == 2


def test_manifest_repository_adds_timestamps_and_preserves_created_at_on_upsert(temp_wiki_root: Path) -> None:
    from datetime import datetime

    repository = ManifestRepository(temp_wiki_root)

    repository.upsert({"wiki_id": "personal-1", "doc_id": "atom-time", "page_type": "atom"})
    created_entry = repository.find("atom-time")

    assert created_entry["created_at"]
    assert created_entry["updated_at"]
    datetime.fromisoformat(created_entry["created_at"].replace("Z", "+00:00"))
    datetime.fromisoformat(created_entry["updated_at"].replace("Z", "+00:00"))

    repository.upsert({"wiki_id": "personal-1", "doc_id": "atom-time", "page_type": "atom", "summary": "updated"})
    updated_entry = repository.find("atom-time")

    assert updated_entry["created_at"] == created_entry["created_at"]
    assert updated_entry["updated_at"] >= created_entry["updated_at"]
    assert updated_entry["summary"] == "updated"


def test_manifest_repository_uses_file_mtime_for_legacy_entry_missing_timestamps(temp_wiki_root: Path) -> None:
    from agent_wiki._compat import UTC
    from datetime import datetime
    import os

    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    page_path = pages_dir / "raw-legacy.md"
    page_path.write_text("# Legacy", encoding="utf-8")
    os.utime(page_path, (1_700_000_000, 1_700_000_000))

    repository = ManifestRepository(temp_wiki_root)
    repository.upsert({
        "wiki_id": "personal-1",
        "doc_id": "raw-legacy",
        "page_type": "raw",
        "canonical_uri": "pages/raw-legacy.md",
    })

    entry = repository.find("raw-legacy")

    assert entry["created_at"] == datetime.fromtimestamp(1_700_000_000, UTC).isoformat().replace("+00:00", "Z")
    assert entry["updated_at"] == entry["created_at"]


def test_manifest_repository_read_all_uses_file_mtime_fallback_for_existing_legacy_entry(temp_wiki_root: Path) -> None:
    from agent_wiki._compat import UTC
    from datetime import datetime
    import json
    import os

    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    page_path = pages_dir / "atom-existing-legacy.md"
    page_path.write_text("# Existing legacy", encoding="utf-8")
    os.utime(page_path, (1_700_000_100, 1_700_000_100))
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        json.dumps({
            "wiki_id": "personal-1",
            "doc_id": "atom-existing-legacy",
            "page_type": "atom",
            "canonical_uri": "pages/atom-existing-legacy.md",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    entry = ManifestRepository(temp_wiki_root).find("atom-existing-legacy")

    assert entry["created_at"] == datetime.fromtimestamp(1_700_000_100, UTC).isoformat().replace("+00:00", "Z")
    assert entry["updated_at"] == entry["created_at"]


def test_manifest_repository_skips_corrupt_lines_with_warning(temp_wiki_root: Path, caplog) -> None:
    manifest_path = temp_wiki_root / "MANIFEST.jsonl"
    manifest_path.write_bytes(
        b'{"wiki_id":"personal-1","doc_id":"raw-good","page_type":"raw"}\n'
        b'\x00\x00\x00\n'
        b'{"wiki_id":"personal-1","doc_id":"raw-after","page_type":"raw"}\n'
    )

    with caplog.at_level(logging.WARNING):
        entries = ManifestRepository(temp_wiki_root).read_all()

    assert [entry["doc_id"] for entry in entries] == ["raw-good", "raw-after"]
    assert "Skipping corrupt manifest line" in caplog.text


def test_manifest_repository_upsert_replaces_file_atomically(temp_wiki_root: Path, monkeypatch) -> None:
    repository = ManifestRepository(temp_wiki_root)
    replaced: list[tuple[Path, Path]] = []

    def fake_replace(source, target) -> None:
        replaced.append((Path(source), Path(target)))
        Path(target).write_text(Path(source).read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr("agent_wiki.infrastructure.storage.manifest_repo.os.replace", fake_replace)

    repository.upsert(
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-atomic",
            "page_type": "raw",
            "canonical_uri": "pages/raw-atomic.md",
        }
    )

    assert replaced
    assert replaced[0][0].parent == temp_wiki_root
    assert replaced[0][1] == temp_wiki_root / "MANIFEST.jsonl"
    assert repository.find("raw-atomic") is not None
