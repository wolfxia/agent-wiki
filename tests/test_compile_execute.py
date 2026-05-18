import json
import time
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_execute import CompileExecuteInput, CompileExecuteService, CompileGeneratedInput
from agent_wiki.application.compile_apply import CompileApplyService, CompileStructuredOutput
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
    assert packet.prepare.proposed_doc_id == "atom-external-sync-ai-cluster-ai-0010"


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


def test_compile_apply_service_parses_structured_json_output(monkeypatch, temp_wiki_root: Path) -> None:
    wiki, _actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-structured-llm")
    wiki = wiki.model_copy(
        update={
            "compile": {
                "llm": {
                    "base_url": "https://llm.example/v1",
                    "api_key_env": "TEST_LLM_API_KEY",
                    "model": "test-model",
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
        captured["json"] = json

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json_module.dumps(
                                    {
                                        "content": "# Structured Atom\n\n## Claims\n- Compiled claim.",
                                        "summary": "Structured summary for retrieval.",
                                        "aliases": ["structured alias"],
                                        "confidence": "medium",
                                        "wikilinks": ["[[related-atom]]"],
                                        "claims": ["Compiled claim."],
                                        "open_questions": ["What changes next?"],
                                        "evidence_coverage": "Covers three raw notes.",
                                    }
                                )
                            }
                        }
                    ]
                }

        return Response()

    json_module = json
    monkeypatch.setenv("TEST_LLM_API_KEY", "secret-token")
    service = CompileApplyService(http_post=fake_post)

    content = service.generate(wiki, packet.prepare)

    assert content == "# Structured Atom\n\n## Claims\n- Compiled claim."
    assert service.last_structured_output is not None
    assert service.last_structured_output.summary == "Structured summary for retrieval."
    assert service.last_structured_output.aliases == ["structured alias"]
    assert service.last_structured_output.confidence == "medium"
    assert service.last_structured_output.wikilinks == ["[[related-atom]]"]
    messages = captured["json"]["messages"]
    assert "Return only valid JSON" in messages[0]["content"]
    assert '"evidence_coverage"' in messages[1]["content"]


def test_compile_apply_service_falls_back_to_plain_markdown(monkeypatch, temp_wiki_root: Path) -> None:
    wiki, _actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-plain-llm")
    wiki = wiki.model_copy(
        update={
            "compile": {
                "llm": {
                    "base_url": "https://llm.example/v1",
                    "api_key_env": "TEST_LLM_API_KEY",
                    "model": "test-model",
                }
            }
        }
    )
    packet = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=_actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float):
        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"choices": [{"message": {"content": "# Plain Atom\n\nClaim: compatible."}}]}

        return Response()

    monkeypatch.setenv("TEST_LLM_API_KEY", "secret-token")
    service = CompileApplyService(http_post=fake_post)

    content = service.generate(wiki, packet.prepare)

    assert content == "# Plain Atom\n\nClaim: compatible."
    assert service.last_structured_output is None


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


def test_compile_apply_service_retries_timeout_then_succeeds(monkeypatch, temp_wiki_root: Path) -> None:
    wiki, _actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-llm-retry-timeout")
    wiki = wiki.model_copy(
        update={
            "compile": {
                "llm": {
                    "base_url": "https://llm.example/v1",
                    "api_key_env": "TEST_LLM_API_KEY",
                    "model": "test-model",
                }
            }
        }
    )
    packet = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=_actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]
    attempts = 0
    slept: list[int] = []

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("request timed out")

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"choices": [{"message": {"content": "# Retry Atom\n\nClaim: retry succeeded."}}]}

        return Response()

    monkeypatch.setenv("TEST_LLM_API_KEY", "secret-token")

    content = CompileApplyService(http_post=fake_post, sleep=slept.append).generate(wiki, packet.prepare)

    assert content == "# Retry Atom\n\nClaim: retry succeeded."
    assert attempts == 3
    assert slept == [10, 30]


def test_compile_apply_service_uses_registry_retry_configuration(monkeypatch, temp_wiki_root: Path) -> None:
    wiki, _actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-llm-configured-retry")
    wiki = wiki.model_copy(
        update={
            "compile": {
                "llm": {
                    "base_url": "https://llm.example/v1",
                    "api_key_env": "TEST_LLM_API_KEY",
                    "model": "test-model",
                    "timeout_seconds": 7,
                    "max_retries": 1,
                    "retry_delays": [4],
                }
            }
        }
    )
    packet = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=_actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]
    attempts = 0
    slept: list[int] = []
    timeouts: list[float] = []

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float):
        nonlocal attempts
        attempts += 1
        timeouts.append(timeout)
        raise TimeoutError("request timed out")

    monkeypatch.setenv("TEST_LLM_API_KEY", "secret-token")

    try:
        CompileApplyService(http_post=fake_post, sleep=slept.append).generate(wiki, packet.prepare)
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected configured retry exhaustion")

    assert attempts == 2
    assert slept == [4]
    assert timeouts == [7, 7]


def test_compile_apply_service_retries_5xx_but_not_4xx(monkeypatch, temp_wiki_root: Path) -> None:
    import httpx

    wiki, _actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-llm-retry-http")
    wiki = wiki.model_copy(
        update={
            "compile": {
                "llm": {
                    "base_url": "https://llm.example/v1",
                    "api_key_env": "TEST_LLM_API_KEY",
                    "model": "test-model",
                }
            }
        }
    )
    packet = CompileExecuteService().prepare_next(
        wiki=wiki,
        actor=_actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]
    statuses = [500, 502, 400]
    slept: list[int] = []

    def fake_post(url: str, *, headers: dict, json: dict, timeout: float):
        status = statuses.pop(0)
        request = httpx.Request("POST", url)
        response = httpx.Response(status, request=request)

        class Response:
            def raise_for_status(self) -> None:
                raise httpx.HTTPStatusError("bad response", request=request, response=response)

            def json(self) -> dict:
                return {}

        return Response()

    monkeypatch.setenv("TEST_LLM_API_KEY", "secret-token")

    try:
        CompileApplyService(http_post=fake_post, sleep=slept.append).generate(wiki, packet.prepare)
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 400
    else:
        raise AssertionError("expected 400 response to escape without retry")

    assert slept == [10, 30]
    assert statuses == []


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
    assert stored["content_state"]["latency_seconds"] >= 0
    assert stored["content_state"]["attempts"] == 1
    assert stored["content_state"]["error_type"] is None


def test_compile_execute_apply_next_persists_structured_metadata(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-structured-apply")

    class StructuredApplyService:
        last_attempts = 1
        last_usage = None
        last_structured_output = None

        def generate(self, wiki, prepare):
            self.last_structured_output = CompileStructuredOutput(
                content="# Structured Apply\n\nClaim: structured metadata persists.",
                summary="Structured metadata summary.",
                aliases=["metadata alias"],
                confidence="high",
                wikilinks=["[[metadata-neighbor]]"],
                claims=["structured metadata persists"],
                open_questions=[],
                evidence_coverage="Three source refs covered.",
            )
            return self.last_structured_output.content

    result = CompileExecuteService(apply_service=StructuredApplyService()).apply_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]

    manifest_entry = next(
        entry for entry in (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8").splitlines()
        if json.loads(entry).get("doc_id") == result.doc_id
    )
    stored = json.loads(manifest_entry)
    assert stored["summary"] == "Structured metadata summary."
    assert stored["aliases"] == ["metadata alias"]
    assert stored["confidence"] == "high"
    assert stored["wikilinks"] == ["[[metadata-neighbor]]"]


def test_compile_execute_apply_next_records_token_usage_when_available(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(temp_wiki_root, problem_cluster="cluster-token-usage")

    class FakeApplyService:
        last_usage = {"prompt_tokens": 17, "completion_tokens": 23, "total_tokens": 40}
        last_attempts = 2

        def generate(self, wiki, prepare):
            return "# Generated Token Usage\n\nClaim: token usage is observable."

    result = CompileExecuteService(apply_service=FakeApplyService()).apply_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=1, priority_filter="P0"),
    )[0]

    stored = ReviewQueueRepository(temp_wiki_root).find(result.item_id)
    assert stored["content_state"]["token_usage"] == {
        "prompt_tokens": 17,
        "completion_tokens": 23,
        "total_tokens": 40,
    }
    assert stored["content_state"]["attempts"] == 2


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
    assert stored["content_state"]["latency_seconds"] >= 0
    assert stored["content_state"]["attempts"] == 1
    assert stored["content_state"]["error_type"] == "timeout"
    assert stored["previous_assigned_to"] == "claude-code"
    assert "assigned_to" not in stored
    assert "claimed_at" not in stored


def test_compile_execute_apply_next_generates_concurrently_but_applies_serially(temp_wiki_root: Path) -> None:
    wiki, actor = _seed_cluster(
        temp_wiki_root,
        topic="imaging-os",
        problem_cluster="cluster-concurrent-a",
        raw_doc_prefix="raw-concurrent-a",
    )
    _seed_cluster(
        temp_wiki_root,
        topic="agent-os",
        problem_cluster="cluster-concurrent-b",
        raw_doc_prefix="raw-concurrent-b",
    )
    generate_windows: list[tuple[str, float, float]] = []
    apply_order: list[str] = []

    class SlowApplyService:
        def generate(self, wiki, prepare):
            start = time.monotonic()
            time.sleep(0.05)
            end = time.monotonic()
            generate_windows.append((prepare.proposed_doc_id, start, end))
            return f"# {prepare.proposed_doc_id}\n\nClaim: concurrent generation."

    service = CompileExecuteService(apply_service=SlowApplyService())
    original_apply_generated = service.apply_generated

    def tracking_apply_generated(*args, **kwargs):
        data = kwargs["data"]
        apply_order.append(data.doc_id)
        return original_apply_generated(*args, **kwargs)

    service.apply_generated = tracking_apply_generated

    results = service.apply_next(
        wiki=wiki,
        actor=actor,
        data=CompileExecuteInput(limit=2, priority_filter="P0", concurrency=2),
    )

    assert [result.status for result in results] == ["committed", "committed"]
    assert len(generate_windows) == 2
    first, second = generate_windows
    assert first[1] < second[2] and second[1] < first[2]
    assert apply_order == [result.doc_id for result in results]
