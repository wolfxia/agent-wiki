import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_compile_analyze_selects_existing_atom_revision(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-source-1",
            topic="testing",
            problem_cluster="cluster-a",
            content="# Source one",
            source_refs=[],
        ),
    )

    existing_atom = temp_wiki_root / "pages" / "atom-existing.md"
    existing_atom.write_text("# Existing atom\n", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        (temp_wiki_root / "MANIFEST.jsonl").read_text()
        + json.dumps(
            {
                "wiki_id": wiki.wiki_id,
                "doc_id": "atom-existing",
                "page_type": "atom",
                "canonical_uri": "pages/atom-existing.md",
                "problem_cluster": "cluster-a",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = compile_service.analyze(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-existing",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-a",
            content="Updated atom content",
            source_refs=["personal-1:raw-source-1"],
        ),
    )

    assert analysis.change_type == "revise"
    assert analysis.target_doc_id == "atom-existing"
    assert analysis.gate == "B"
