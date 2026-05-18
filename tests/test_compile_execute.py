import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_execute import CompileExecuteInput, CompileExecuteService, CompileGeneratedInput
from agent_wiki.application.compile_apply import CompileApplyService
from agent_wiki.application.compile_suggest import CompileSuggestService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository


def _wiki(temp_wiki_root: Path):
    return RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )


def _seed_cluster(
    temp_wiki_root: Path,
    topic: str = "imaging-os",
    problem_cluster: str = "cluster-execute",
    raw_doc_prefix: str = "raw-service-execute",
):
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
                doc_id=f"{raw_doc_prefix}-{index}",
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


def test_compile_execute_priority_filter_p0_prefers_p0_when_available(temp_wiki_root: Path) -> None:
    p0_wiki, actor = _seed_cluster(
        temp_wiki_root,
        topic="imaging-os",
        problem_cluster="cluster-p0",
        raw_doc_prefix="raw-service-p0",
    )
    _seed_cluster(
        temp_wiki_root,
        topic="misc-topic",
        problem_cluster="cluster-p1",
        raw_doc_prefix="raw-service-p1",
    )

    results = CompileExecuteService().prepare_next(
        wiki=p0_wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )

    assert len(results) == 1
    assert results[0].priority_label == "P0"
    assert results[0].fallback_priority is None
    assert results[0].item_id == "compile_suggestion:imaging-os:cluster-p0:0001"


def test_compile_execute_priority_filter_p0_falls_back_to_p1_when_p0_empty(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(temp_wiki_root, topic="misc-topic", problem_cluster="cluster-p1-only")

    results = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )

    assert len(results) == 1
    assert results[0].priority_label == "P1"
    assert results[0].fallback_priority == "P1"
    assert results[0].item_id == "compile_suggestion:misc-topic:cluster-p1-only:0001"


def test_compile_execute_priority_filter_p0_returns_empty_when_p0_and_p1_empty(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    results = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )

    assert results == []


def test_compile_execute_parses_legacy_item_id_with_colons_in_problem_cluster(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(
        temp_wiki_root,
        topic="external_sync",
        problem_cluster="AI:cluster:AI",
        raw_doc_prefix="raw-external-sync-ai",
    )
    queue_path = temp_wiki_root / "review_queue.jsonl"
    queue_path.write_text(
        json.dumps(
            {
                "item_id": "compile_suggestion:external_sync:AI:cluster:AI:0010",
                "item_type": "compile_suggestion",
                "raw_doc_ids": ["raw-external-sync-ai-0", "raw-external-sync-ai-1", "raw-external-sync-ai-2"],
                "status": "open",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    packet = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1),
    )[0]

    assert packet.prepare.topic == "external_sync"
    assert packet.prepare.problem_cluster == "AI:cluster:AI"
    assert packet.prepare.proposed_doc_id == "atom-external_sync-AI-cluster-AI-0010"


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


def test_compile_apply_service_calls_openai_compatible_api(monkeypatch, temp_wiki_root: Path) -> None:
    wiki, _actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-llm")
    wiki = wiki.model_copy(
        update={
            "compile": {
                "llm": {
                    "base_url": "https://llm.example/v1",
                    "api_key_env": "TEST_LLM_API_KEY",
                    "model": "test-model",
                    "max_tokens": 1234,
                    "timeout_seconds": 12,
                }
            }
        }
    )
    packet = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=_actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]
    captured: dict[str, object] = {}

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"choices": [{"message": {"content": "# Generated Atom\n\nClaim: compiled."}}]}

        return Response()

    monkeypatch.setenv("TEST_LLM_API_KEY", "secret-token")

    content = CompileApplyService(http_post=fake_post).generate(wiki, packet.prepare)

    assert content == "# Generated Atom\n\nClaim: compiled."
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["max_tokens"] == 1234
    assert "create_retrieval_ready_atom" in captured["json"]["messages"][1]["content"]
    assert captured["timeout"] == 12


def test_compile_apply_service_defaults_timeout_to_120(monkeypatch, temp_wiki_root: Path) -> None:
    wiki, _actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-llm-default-timeout")
    wiki = wiki.model_copy(
        update={
            "compile": {
                "llm": {
                    "base_url": "https://llm.example/v1",
                    "api_key_env": "TEST_LLM_API_KEY",
                    "model": "test-model",
                    "max_tokens": 1234,
                }
            }
        }
    )
    packet = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=_actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]
    captured: dict[str, object] = {}

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float):
        captured["timeout"] = timeout

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"choices": [{"message": {"content": "# Generated Atom\n\nClaim: compiled."}}]}

        return Response()

    monkeypatch.setenv("TEST_LLM_API_KEY", "secret-token")

    CompileApplyService(http_post=fake_post).generate(wiki, packet.prepare)

    assert captured["timeout"] == 120


def test_compile_execute_apply_next_generates_applies_and_resolves(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-apply-next")

    class FakeApplyService:
        def generate(self, wiki, prepare):
            assert prepare.proposed_doc_id == "atom-imaging-os-cluster-apply-next-0001"
            return "# Generated Apply Next\n\nClaim: single command compile."

    results = CompileExecuteService(apply_service=FakeApplyService()).apply_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )

    assert len(results) == 1
    result = results[0]
    assert result.item_id == "compile_suggestion:imaging-os:cluster-apply-next:0001"
    assert result.status == "committed"
    assert result.queue_status == "resolved"
    assert result.doc_id == "atom-imaging-os-cluster-apply-next-0001"
    assert result.fallback_priority is None
    assert (temp_wiki_root / "pages" / "atom-imaging-os-cluster-apply-next-0001.md").read_text(encoding="utf-8").startswith("# Generated Apply Next")
    stored = ReviewQueueRepository(temp_wiki_root).find(result.item_id)
    assert stored["status"] == "resolved"
    assert stored["content_state"]["compiled_doc_id"] == result.doc_id


def test_compile_execute_apply_next_reports_fallback_priority(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(temp_wiki_root, topic="misc-topic", problem_cluster="cluster-apply-p1")

    class FakeApplyService:
        def generate(self, wiki, prepare):
            assert prepare.proposed_doc_id == "atom-misc-topic-cluster-apply-p1-0001"
            return "# Generated Apply P1\n\nClaim: fallback compile."

    results = CompileExecuteService(apply_service=FakeApplyService()).apply_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )

    assert len(results) == 1
    result = results[0]
    assert result.item_id == "compile_suggestion:misc-topic:cluster-apply-p1:0001"
    assert result.status == "committed"
    assert result.queue_status == "resolved"
    assert result.doc_id == "atom-misc-topic-cluster-apply-p1-0001"
    assert result.fallback_priority == "P1"


def test_compile_execute_apply_next_marks_failed_and_continues(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-apply-fail")

    class FailingApplyService:
        def generate(self, wiki, prepare):
            raise RuntimeError("LLM timed out")

    results = CompileExecuteService(apply_service=FailingApplyService()).apply_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].queue_status == "failed"
    stored = ReviewQueueRepository(temp_wiki_root).find(results[0].item_id)
    assert stored["status"] == "failed"
    assert stored["last_error"] == "LLM timed out"
