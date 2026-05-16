import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.application.relations import RelationsService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_co_occurrence_detects_relation_candidates(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # Create two pages that will co-occur in query results
    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-rel-1", topic="caching", problem_cluster="cluster-rel",
            content="# Raw rel one", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-rel-1", page_type="atom", topic="caching",
            problem_cluster="cluster-rel",
            content="# Atom rel one\n\nCaching strategies for performance.",
            source_refs=["personal-1:raw-rel-1"],
        ),
    )
    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-rel-2", topic="caching", problem_cluster="cluster-rel",
            content="# Raw rel two", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-rel-2", page_type="atom", topic="caching",
            problem_cluster="cluster-rel",
            content="# Atom rel two\n\nCaching invalidation for performance.",
            source_refs=["personal-1:raw-rel-2"],
        ),
    )

    # Run multiple queries that produce both pages as hits
    for _ in range(3):
        query_service.execute(
            wiki=wiki, actor=actor,
            data=QueryInput(query="caching performance"),
        )

    relations_service = RelationsService()
    candidates = relations_service.detect_co_occurrences(wiki, threshold=2)

    assert len(candidates) >= 1
    pair = candidates[0]
    assert "atom-rel-1" in pair["doc_ids"]
    assert "atom-rel-2" in pair["doc_ids"]
    assert pair["co_occurrence_count"] >= 2


def test_cross_reference_detects_relation_candidates(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    # Create pages with shared source_refs
    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-xref-1", topic="auth", problem_cluster="cluster-xref",
            content="# Raw xref", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-xref-1", page_type="atom", topic="auth",
            problem_cluster="cluster-xref",
            content="# Atom xref one\n\nAuthentication flow.",
            source_refs=["personal-1:raw-xref-1"],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-xref-2", page_type="atom", topic="auth",
            problem_cluster="cluster-xref",
            content="# Atom xref two\n\nAuthorization flow.",
            source_refs=["personal-1:raw-xref-1"],
        ),
    )

    relations_service = RelationsService()
    candidates = relations_service.detect_cross_references(wiki)

    assert len(candidates) >= 1
    pair = candidates[0]
    assert "atom-xref-1" in pair["doc_ids"]
    assert "atom-xref-2" in pair["doc_ids"]
    assert pair["shared_refs"]
