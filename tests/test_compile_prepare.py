from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_prepare import CompilePrepareInput, CompilePrepareService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.validators import validate_doc_id


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


def test_compile_prepare_proposes_valid_normalized_doc_id_for_mixed_case_cluster(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-external-sync-ai-1",
            topic="external_sync",
            problem_cluster="AI:cluster:AI",
            content="# External Sync AI\n\nClaim: Mixed case clusters should compile.",
            source_refs=[],
        ),
    )

    result = CompilePrepareService().prepare(
        wiki,
        actor,
        CompilePrepareInput(topic="external_sync", problem_cluster="AI:cluster:AI", sub_cluster_index=17),
    )

    assert result.proposed_doc_id == "atom-external-sync-ai-cluster-ai-0017"
    validate_doc_id(result.proposed_doc_id)


def test_compile_prepare_uses_dynamic_token_budget_and_sentence_level_claims(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    capture = CaptureRawService()
    long_paragraph = " ".join([f"sentence-{index} with service pipeline evidence." for index in range(500)])
    for index in range(3):
        capture.execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-budget-{index}",
                topic="vision-os",
                problem_cluster="token-budget",
                summary=f"summary {index}",
                content=(
                    f"# Raw Budget {index}\n\n"
                    f"Service pipeline {index} improves retrieval fidelity.\n\n"
                    f"Key metric {index}: latency dropped to {index + 10}ms.\n\n"
                    f"{long_paragraph}"
                ),
                source_refs=[],
            ),
        )

    result = CompilePrepareService().prepare(
        wiki,
        actor,
        CompilePrepareInput(topic="vision-os", problem_cluster="token-budget", max_items=3),
    )

    assert result.items[0].claims
    assert any("Service pipeline 0 improves retrieval fidelity." in claim for claim in result.items[0].claims)
    assert any("Key metric 0: latency dropped to 10ms." in claim for claim in result.items[0].claims)
    assert len(result.items[0].content_preview) > 1200
    assert len(result.items[0].content_preview) <= 3000


def test_compile_prepare_extracts_generic_claim_sentences_without_domain_hardcoding(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-generic-claim-1",
            topic="platform",
            problem_cluster="claim-extraction",
            content=(
                "# Generic Claim\n\n"
                "storage pipeline improves retrieval fidelity.\n\n"
                "supporting context without metrics or named entities."
            ),
            source_refs=[],
        ),
    )

    result = CompilePrepareService().prepare(
        wiki,
        actor,
        CompilePrepareInput(topic="platform", problem_cluster="claim-extraction", max_items=1),
    )

    assert "storage pipeline improves retrieval fidelity." in result.items[0].claims


def test_compile_prepare_strips_yaml_frontmatter_before_claim_extraction(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-frontmatter-claim-1",
            topic="compile-frontmatter",
            problem_cluster="claim-extraction",
            summary="frontmatter should not become claims",
            content="placeholder",
            source_refs=[],
        ),
    )
    page_path = temp_wiki_root / "pages" / "raw-frontmatter-claim-1.md"
    noisy_frontmatter = "\n".join(
        [
            "---",
            "doc_id: raw-frontmatter-claim-1",
            "source_refs:",
            *[f"  - personal-1:raw-source-{index}" for index in range(700)],
            "confidence: medium",
            "version: v03",
            "---",
        ]
    )
    page_path.write_text(
        noisy_frontmatter
        + "\n# Raw Frontmatter Claim\n\n"
        + "Storage pipeline improves retrieval fidelity.\n\n"
        + "Key metric: prompt size stays under 8KB.",
        encoding="utf-8",
    )

    result = CompilePrepareService().prepare(
        wiki,
        actor,
        CompilePrepareInput(topic="compile-frontmatter", problem_cluster="claim-extraction", max_items=1),
    )
    item = result.items[0]

    assert "Storage pipeline improves retrieval fidelity." in item.claims
    assert "Key metric: prompt size stays under 8KB." in item.claims
    assert all("source_refs" not in claim for claim in item.claims)
    assert all("raw-source-" not in claim for claim in item.claims)
    assert item.content_preview.startswith("# Raw Frontmatter Claim")
    assert "source_refs" not in item.content_preview


def test_compile_prepare_includes_existing_atom_summaries_for_dedup_context(temp_wiki_root: Path) -> None:
    from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="mcp")
    capture = CaptureRawService()
    capture.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-context-1",
            topic="agent-os",
            problem_cluster="context-window",
            content="# Raw context\n\nAgents need context windows.",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CompileUpdateInput(
            doc_id="atom-context-existing",
            page_type="atom",
            topic="agent-os",
            problem_cluster="context-window",
            summary="Same-cluster atom summary for context dedup.",
            confidence="high",
            aliases=["context"],
            wikilinks=["[[raw-context-1]]"],
            content="# Existing Atom\n\n## Claims\n- Existing context window guidance.\n\n## Evidence\n- Prior raw evidence.",
            source_refs=["personal-1:raw-context-1"],
        ),
    )

    result = CompilePrepareService().prepare(
        wiki,
        actor,
        CompilePrepareInput(topic="agent-os", problem_cluster="context-window", max_items=1),
    )

    assert result.existing_atom_summaries == [
        {
            "doc_id": "atom-context-existing",
            "summary": "Same-cluster atom summary for context dedup.",
            "problem_cluster": "context-window",
        }
    ]
