import json
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
