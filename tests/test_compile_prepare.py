from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_prepare import CompilePrepareInput, CompilePrepareService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_compile_prepare_returns_cluster_raw_sources_with_source_refs(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    capture = CaptureRawService()
    for index in range(3):
        capture.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-prepare-{index}",
                topic="edge-ai",
                problem_cluster="imaging",
                summary=f"summary {index}",
                content=f"# Raw Prepare {index}\n\nClaim {index}: Edge imaging agents need retrieval-ready memory. Evidence body {index}.",
                source_refs=[],
            ),
        )

    result = CompilePrepareService().prepare(
        wiki,
        actor,
        CompilePrepareInput(topic="edge-ai", problem_cluster="imaging", max_items=2),
    )

    assert result.topic == "edge-ai"
    assert result.problem_cluster == "imaging"
    assert result.total_raw_count == 3
    assert result.sub_cluster_id == "edge-ai_imaging_0001"
    assert result.proposed_page_type == "atom"
    assert result.proposed_doc_id == "atom-edge-ai-imaging-0001"
    assert result.agent_objective == "create_retrieval_ready_atom"
    assert result.source_refs == ["personal-1:raw-prepare-0", "personal-1:raw-prepare-1"]
    assert [item.doc_id for item in result.items] == ["raw-prepare-0", "raw-prepare-1"]
    assert result.items[0].claims == ["Claim 0: Edge imaging agents need retrieval-ready memory."]
    assert result.relationship_hints[0]["relationship"] == "same_topic_cluster"


def test_compile_prepare_surfaces_contradiction_markers_for_agent_reasoning(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-contradiction-1",
            topic="agent-memory",
            problem_cluster="truth-zone",
            content="# Contradiction\n\nClaim: Truth zone should be optimized for agents. However, this contradicts treating compiled pages as blog posts.",
            source_refs=[],
        ),
    )

    result = CompilePrepareService().prepare(
        wiki,
        actor,
        CompilePrepareInput(topic="agent-memory", problem_cluster="truth-zone"),
    )

    assert result.contradiction_markers
    assert result.contradiction_markers[0]["doc_id"] == "raw-contradiction-1"
    assert "contradicts" in result.contradiction_markers[0]["text"]


def test_compile_prepare_accepts_explicit_doc_ids(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    capture = CaptureRawService()
    for index in range(3):
        capture.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-explicit-{index}",
                topic="infra",
                problem_cluster="queues",
                content=f"# Explicit {index}",
                source_refs=[],
            ),
        )

    result = CompilePrepareService().prepare(
        wiki,
        actor,
        CompilePrepareInput(
            topic="infra",
            problem_cluster="queues",
            doc_ids=["raw-explicit-2", "raw-explicit-0"],
        ),
    )

    assert [item.doc_id for item in result.items] == ["raw-explicit-2", "raw-explicit-0"]
    assert result.source_refs == ["personal-1:raw-explicit-2", "personal-1:raw-explicit-0"]
