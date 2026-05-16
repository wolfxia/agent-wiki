import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.linting import LintService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_lint_detects_missing_page_for_manifest_entry(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    lint_service = LintService()

    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        json.dumps(
            {
                "wiki_id": "personal-1",
                "doc_id": "raw-missing-page",
                "page_type": "raw",
                "canonical_uri": "pages/raw-missing-page.md",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = lint_service.run(wiki)

    assert result.ok is False
    assert any("missing page" in issue for issue in result.issues)


def test_lint_passes_for_basic_committed_capture(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    lint_service = LintService()

    capture_service.execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-lint-1",
            topic="testing",
            problem_cluster="cluster-l1",
            content="# Raw lint one",
            source_refs=[],
        ),
    )

    result = lint_service.run(wiki)

    assert result.ok is True
    assert result.issues == []
