import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_execute import CompileExecuteInput, CompileExecuteService, CompileGeneratedInput
from agent_wiki.application.compile_suggest import CompileSuggestService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository


def _wiki(temp_wiki_root: Path):
    return RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )


def _seed_cluster(temp_wiki_root: Path, topic: str = "imaging-os", problem_cluster: str = "cluster-execute"):
    wiki = _wiki(temp_wiki_root)
    (temp_wiki_root / "purpose.md").write_text(
        "# Purpose\n\n## Topics\n\n- imaging-os\n- agent-os\n",
        encoding="utf-8",
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    for index in range(3):
        CaptureRawService().execute(
            wiki=wiki,
            actor=actor,
            data=CaptureRawInput(
                doc_id=f"raw-service-execute-{index}",
                topic=topic,
                problem_cluster=problem_cluster,
                content=f"# Raw service execute {index}\n\nClaim: service execute {index}.",
                source_refs=[],
            ),
        )
    CompileSuggestService().detect_and_enqueue(wiki)
    return wiki, actor


def test_compile_execute_claims_suggestion_and_returns_prepare_packet(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(temp_wiki_root)

    results = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )

    assert len(results) == 1
    result = results[0]
    assert result.item_id == "compile_suggestion:imaging-os:cluster-execute:0001"
    assert result.priority_label == "P0"
    assert result.prepare.agent_objective == "create_retrieval_ready_atom"
    assert result.prepare.source_refs == [
        "personal-1:raw-service-execute-0",
        "personal-1:raw-service-execute-1",
        "personal-1:raw-service-execute-2",
    ]
    assert ReviewQueueRepository(temp_wiki_root).find(result.item_id)["status"] == "assigned"


def test_compile_execute_apply_generated_content_resolves_suggestion(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-apply")
    packet = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]

    result = CompileExecuteService().apply_generated(
        wiki=wiki,
        actor=actor,
        data=CompileGeneratedInput(
            item_id=packet.item_id,
            doc_id=packet.prepare.proposed_doc_id,
            page_type=packet.prepare.proposed_page_type,
            topic=packet.prepare.topic,
            problem_cluster=packet.prepare.problem_cluster,
            content="# Atom service apply\n\nClaim: compiled by external agent.",
            source_refs=packet.prepare.source_refs,
        ),
    )

    assert result.status == "committed"
    stored = ReviewQueueRepository(temp_wiki_root).find(packet.item_id)
    assert stored["status"] == "resolved"
    assert stored["content_state"]["compiled_doc_id"] == packet.prepare.proposed_doc_id
    assert (temp_wiki_root / "pages" / f"{packet.prepare.proposed_doc_id}.md").exists()


def test_compile_execute_apply_generated_marks_suggestion_failed_on_error(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-fail")
    packet = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]

    try:
        CompileExecuteService().apply_generated(
            wiki=wiki,
            actor=actor,
            data=CompileGeneratedInput(
                item_id=packet.item_id,
                doc_id="Invalid Doc Id",
                page_type=packet.prepare.proposed_page_type,
                topic=packet.prepare.topic,
                problem_cluster=packet.prepare.problem_cluster,
                content="# Invalid",
                source_refs=packet.prepare.source_refs,
            ),
        )
    except ValueError:
        pass

    stored = ReviewQueueRepository(temp_wiki_root).find(packet.item_id)
    assert stored["status"] == "failed"
    assert "Invalid Doc Id" in stored["last_error"]
