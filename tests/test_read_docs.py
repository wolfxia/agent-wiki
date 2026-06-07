from pathlib import Path

from agent_wiki.application.read_docs import WikiReadService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


def test_get_doc_strips_nested_yaml_frontmatter(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "raw-nested-frontmatter.md").write_text(
        "---\ntitle: outer\n---\n---\nsource: import\n---\n# Body\n\nExact text.",
        encoding="utf-8",
    )
    ManifestRepository(temp_wiki_root).upsert(
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-nested-frontmatter",
            "page_type": "raw",
            "canonical_uri": "pages/raw-nested-frontmatter.md",
        }
    )

    result = WikiReadService().get_doc(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp"),
        doc_id="raw-nested-frontmatter",
    )

    assert result.content == "# Body\n\nExact text."


def test_inbound_refs_matches_wikilink_aliases_and_anchors_exactly(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    manifest = ManifestRepository(temp_wiki_root)
    manifest.batch_upsert(
        [
            {
                "wiki_id": "personal-1",
                "doc_id": "raw-target",
                "page_type": "raw",
                "canonical_uri": "pages/raw-target.md",
            },
            {
                "wiki_id": "personal-1",
                "doc_id": "atom-linking",
                "page_type": "atom",
                "canonical_uri": "pages/atom-linking.md",
                "source_refs": [],
                "wikilinks": ["[[raw-target#section|Target]]"],
            },
            {
                "wiki_id": "personal-1",
                "doc_id": "atom-near-miss",
                "page_type": "atom",
                "canonical_uri": "pages/atom-near-miss.md",
                "source_refs": ["personal-1:raw-target-extra"],
                "wikilinks": ["[[raw-target-extra]]"],
            },
        ]
    )

    result = WikiReadService().inbound_refs(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp"),
        doc_id="raw-target",
    )

    assert result.ref_count == 1
    assert result.refs[0]["doc_id"] == "atom-linking"
    assert result.refs[0]["fields"] == ["wikilinks"]
