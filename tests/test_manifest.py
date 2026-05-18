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
