import json
from pathlib import Path

from agent_wiki.application.compile_apply import CompileApplyService
from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_compile_apply_writes_atom_and_operation_log(temp_wiki_root: Path) -> None:
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
            doc_id="raw-source-2",
            topic="testing",
            problem_cluster="cluster-b",
            content="# Source two",
            source_refs=[],
        ),
    )

    result = compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-new",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-b",
            content="# Atom new\n\nCompiled",
            source_refs=["personal-1:raw-source-2"],
        ),
    )

    assert result.status == "committed"
    assert (temp_wiki_root / "pages" / "atom-new.md").exists()
    assert (temp_wiki_root / "operation_log.jsonl").exists()
    operation = json.loads((temp_wiki_root / "operation_log.jsonl").read_text().strip())
    assert operation["operation"] == "compile_update"
    assert operation["doc_id"] == "atom-new"


def test_compile_apply_rejects_missing_raw_source_ref(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    try:
        compile_service.apply(
            wiki=wiki,
            actor=actor,
            data=CompileUpdateInput(
                doc_id="atom-invalid",
                page_type="atom",
                topic="testing",
                problem_cluster="cluster-b",
                content="# Invalid",
                source_refs=["personal-1:missing-raw"],
            ),
        )
    except ValueError as error:
        assert "source_refs must point to existing raw pages" in str(error)
    else:
        raise AssertionError("expected source ref validation failure")


def test_compile_apply_denied_when_actor_gate_insufficient(temp_wiki_root: Path) -> None:
    from agent_wiki.bootstrap.registry_loader import PermissionConfig

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={
            "workspace_path": str(temp_wiki_root),
            "permissions": [
                PermissionConfig(
                    actor_type="agent",
                    actor_id="low-gate-agent",
                    allowed_operations=["capture_raw", "compile_update"],
                    max_gate="A",
                    allowed_page_types=["raw", "atom", "synthesis"],
                )
            ],
        }
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="low-gate-agent", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-gate-1", topic="testing", problem_cluster="cluster-gate",
            content="# Raw gate", source_refs=[],
        ),
    )

    try:
        compile_service.apply(
            wiki=wiki,
            actor=actor,
            data=CompileUpdateInput(
                doc_id="atom-gate-1", page_type="atom", topic="testing",
                problem_cluster="cluster-gate",
                content="# Atom gate",
                source_refs=["personal-1:raw-gate-1"],
            ),
        )
    except PermissionError as error:
        assert "gate" in str(error).lower()
    else:
        raise AssertionError("expected gate enforcement failure")



def test_compile_apply_rejects_path_traversal_doc_id(temp_wiki_root: Path) -> None:
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
            doc_id="raw-traversal-1",
            topic="testing",
            problem_cluster="cluster-traversal",
            content="# Raw traversal",
            source_refs=[],
        ),
    )

    try:
        compile_service.apply(
            wiki=wiki,
            actor=actor,
            data=CompileUpdateInput(
                doc_id="../outside",
                page_type="atom",
                topic="testing",
                problem_cluster="cluster-traversal",
                content="# traversal",
                source_refs=["personal-1:raw-traversal-1"],
            ),
        )
    except ValueError as error:
        assert "doc_id" in str(error)
    else:
        raise AssertionError("expected doc_id validation failure")


def test_compile_apply_persists_retrieval_ready_metadata(temp_wiki_root: Path) -> None:
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
            doc_id="raw-schema-1",
            topic="testing",
            problem_cluster="cluster-schema",
            content="# Raw schema",
            source_refs=[],
        ),
    )

    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-schema-1",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-schema",
            summary="Schema summary.",
            aliases=["schema alias"],
            confidence="high",
            contested=True,
            wikilinks=["raw-schema-1"],
            content="# Atom schema\n\nCompiled schema body.",
            source_refs=["personal-1:raw-schema-1"],
        ),
    )

    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    assert "confidence" in manifest
    assert "aliases" in manifest
    assert "wikilinks" in manifest


def test_parse_structured_output_extracts_json_from_preamble_and_code_fence() -> None:
    service = CompileApplyService()

    result = service._parse_structured_output(
        """前置说明\n<think>reasoning</think>\n```json
{
  \"content\": \"# 标题\\n\\n## Claims\\n- claim\\n\\n## Evidence\\n- evidence\",
  \"summary\": \"摘要\",
  \"confidence\": \"high\"
}
```\n后置说明"""
    )

    assert result is not None
    assert result.summary == "摘要"
    assert result.confidence == "high"


def test_parse_structured_output_returns_none_for_garbage() -> None:
    service = CompileApplyService()

    result = service._parse_structured_output("not json at all")

    assert result is None
