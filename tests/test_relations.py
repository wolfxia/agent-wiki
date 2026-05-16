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


def test_co_occurrence_enqueues_signal_candidates(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-coq-1", topic="infra", problem_cluster="cluster-coq",
            content="# Raw coq one", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-coq-1", page_type="atom", topic="infra",
            problem_cluster="cluster-coq",
            content="# Atom coq one\n\nInfra scaling patterns.",
            source_refs=["personal-1:raw-coq-1"],
        ),
    )
    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-coq-2", topic="infra", problem_cluster="cluster-coq",
            content="# Raw coq two", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-coq-2", page_type="atom", topic="infra",
            problem_cluster="cluster-coq",
            content="# Atom coq two\n\nInfra scaling limits.",
            source_refs=["personal-1:raw-coq-2"],
        ),
    )

    for _ in range(3):
        query_service.execute(
            wiki=wiki, actor=actor,
            data=QueryInput(query="infra scaling"),
        )

    relations_service = RelationsService()
    relations_service.detect_and_enqueue_co_occurrences(wiki, threshold=2)

    queue_path = temp_wiki_root / "review_queue.jsonl"
    entries = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    signals = [e for e in entries if e.get("item_type") == "signal_candidate"]
    assert len(signals) >= 1
    assert signals[0]["relation_type"] == "co_occurrence"


def test_cross_reference_enqueues_signal_candidates(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-xrq-1", topic="db", problem_cluster="cluster-xrq",
            content="# Raw xrq", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-xrq-1", page_type="atom", topic="db",
            problem_cluster="cluster-xrq",
            content="# Atom xrq one\n\nDB indexing.",
            source_refs=["personal-1:raw-xrq-1"],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-xrq-2", page_type="atom", topic="db",
            problem_cluster="cluster-xrq",
            content="# Atom xrq two\n\nDB queries.",
            source_refs=["personal-1:raw-xrq-1"],
        ),
    )

    relations_service = RelationsService()
    relations_service.detect_and_enqueue_cross_references(wiki)

    queue_path = temp_wiki_root / "review_queue.jsonl"
    entries = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    signals = [e for e in entries if e.get("item_type") == "signal_candidate"]
    assert len(signals) >= 1
    assert signals[0]["relation_type"] == "cross_reference"
