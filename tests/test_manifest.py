from pathlib import Path

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
