import json
import logging
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.infrastructure.repair.raw_metadata_repair import RawMetadataRepairService


def test_raw_metadata_repair_backfills_imported_raw_pages(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "pending-heavy-1.md").write_text(
        "# Pending Heavy One\n\nImported raw body.", encoding="utf-8"
    )
    pending_root = temp_wiki_root / ".agent-wiki"
    pending_root.mkdir(exist_ok=True)
    (pending_root / "pending_manifest.jsonl").write_text(
        json.dumps(
            {
                "doc_id": "pending-heavy-1",
                "page_type": "raw",
                "vault_relative_path": "01-知识/input/pending-heavy-1.md",
                "adapter_metadata": {"vault_relative_path": "01-知识/input/pending-heavy-1.md"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    repaired = RawMetadataRepairService().repair(wiki)

    assert repaired["repaired_count"] >= 1
    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    assert "pending-heavy-1" in manifest
    assert '"topic":' in manifest


def test_raw_metadata_repair_batches_manifest_updates(temp_wiki_root: Path, monkeypatch) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages_root = temp_wiki_root / "pages"
    pages_root.mkdir(exist_ok=True)
    pending_root = temp_wiki_root / ".agent-wiki"
    pending_root.mkdir(exist_ok=True)
    pending_entries = []
    for index in range(3):
        doc_id = f"pending-batch-{index}"
        (pages_root / f"{doc_id}.md").write_text(f"# Pending {index}\n\nBody.", encoding="utf-8")
        pending_entries.append({"doc_id": doc_id, "page_type": "raw"})
    (pending_root / "pending_manifest.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in pending_entries) + "\n",
        encoding="utf-8",
    )

    batch_sizes: list[int] = []
    upsert_calls: list[dict] = []

    def fake_batch_upsert(self, entries):
        batch_sizes.append(len(entries))
        self._write_all(entries)

    def fake_upsert(self, entry):
        upsert_calls.append(entry)
        raise AssertionError("repair should batch manifest writes")

    monkeypatch.setattr("agent_wiki.infrastructure.storage.manifest_repo.ManifestRepository.batch_upsert", fake_batch_upsert)
    monkeypatch.setattr("agent_wiki.infrastructure.storage.manifest_repo.ManifestRepository.upsert", fake_upsert)

    result = RawMetadataRepairService().repair(wiki)

    assert result["repaired_count"] == 3
    assert batch_sizes == [3]
    assert upsert_calls == []


def test_raw_metadata_repair_batches_runtime_index_updates(temp_wiki_root: Path, monkeypatch) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages_root = temp_wiki_root / "pages"
    pages_root.mkdir(exist_ok=True)
    pending_root = temp_wiki_root / ".agent-wiki"
    pending_root.mkdir(exist_ok=True)
    pending_entries = []
    for index in range(3):
        doc_id = f"pending-runtime-{index}"
        (pages_root / f"{doc_id}.md").write_text(f"# Pending Runtime {index}\n\nBody.", encoding="utf-8")
        pending_entries.append({"doc_id": doc_id, "page_type": "raw"})
    (pending_root / "pending_manifest.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in pending_entries) + "\n",
        encoding="utf-8",
    )

    retrieval_batch_sizes: list[int] = []
    fts_batch_sizes: list[int] = []

    def fake_append_raw_cards(self, wiki_id, cards):
        retrieval_batch_sizes.append(len(cards))

    def fake_append_raw_card(self, wiki_id, data):
        raise AssertionError("repair should batch retrieval index writes")

    def fake_batch_upsert(self, items):
        fts_batch_sizes.append(len(items))

    def fake_fts_upsert(self, doc_id, payload):
        raise AssertionError("repair should batch FTS writes")

    monkeypatch.setattr("agent_wiki.infrastructure.retrieval.retrieval_index.RetrievalIndexRepository.append_raw_cards", fake_append_raw_cards)
    monkeypatch.setattr("agent_wiki.infrastructure.retrieval.retrieval_index.RetrievalIndexRepository.append_raw_card", fake_append_raw_card)
    monkeypatch.setattr("agent_wiki.infrastructure.retrieval.sqlite_fts.SQLiteFTSIndexProvider.batch_upsert", fake_batch_upsert)
    monkeypatch.setattr("agent_wiki.infrastructure.retrieval.sqlite_fts.SQLiteFTSIndexProvider.upsert", fake_fts_upsert)

    result = RawMetadataRepairService().repair(wiki)

    assert result["repaired_count"] == 3
    assert retrieval_batch_sizes == [3]
    assert fts_batch_sizes == [3]


def test_raw_metadata_repair_skips_corrupt_pending_entries(temp_wiki_root: Path, caplog) -> None:
    pending_path = temp_wiki_root / ".agent-wiki" / "pending_manifest.jsonl"
    pending_path.parent.mkdir(exist_ok=True)
    pending_path.write_bytes(
        b'{"doc_id":"pending-good","page_type":"raw"}\n'
        b'\x00\x00\x00\n'
        b'{"doc_id":"pending-after","page_type":"raw"}\n'
    )

    with caplog.at_level(logging.WARNING):
        entries = RawMetadataRepairService()._read_pending_entries(pending_path)

    assert [entry["doc_id"] for entry in entries] == ["pending-good", "pending-after"]
    assert "Skipping corrupt pending manifest line" in caplog.text
