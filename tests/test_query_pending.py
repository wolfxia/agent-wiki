import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_query_excludes_pending_truth_zone_by_default(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-query-4",
            topic="testing",
            problem_cluster="cluster-q4",
            content="# Raw pending source",
            source_refs=[],
        ),
    )

    pending_root = temp_wiki_root / ".agent-wiki"
    pending_root.mkdir(exist_ok=True)
    (pending_root / "pending_manifest.jsonl").write_text(
        json.dumps(
            {
                "wiki_id": "personal-1",
                "doc_id": "atom-pending-1",
                "page_type": "atom",
                "canonical_uri": "pages/atom-pending-1.md",
                "status": "pending",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (temp_wiki_root / "pages" / "atom-pending-1.md").write_text(
        "# Pending atom\n\nPending truth zone content.", encoding="utf-8"
    )

    default_result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="pending truth zone content"),
    )
    included_result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="pending truth zone content", include_pending=True),
    )

    assert all(hit.doc_id != "atom-pending-1" for hit in default_result.hits)
    assert any(hit.doc_id == "atom-pending-1" for hit in included_result.hits)
