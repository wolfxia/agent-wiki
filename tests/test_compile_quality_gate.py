from agent_wiki.application.compile_execute import CompileGeneratedInput
from agent_wiki.application.compile_quality_gate import CompileQualityGate


def test_compile_quality_gate_rejects_missing_required_fields() -> None:
    gate = CompileQualityGate()

    try:
        gate.evaluate(
            CompileGeneratedInput(
                item_id="compile_suggestion:test:0001",
                doc_id="atom-test-0001",
                page_type="atom",
                topic="testing",
                problem_cluster="gate",
                content="# Test\n\n## Claims\n- raw-1\n\n## Evidence\n- proof",
                source_refs=["personal-1:raw-1"],
                summary=None,
                confidence=None,
            )
        )
    except ValueError as exc:
        assert "quality gate" in str(exc).lower()
    else:
        raise AssertionError("expected quality gate rejection")


def test_compile_quality_gate_returns_warning_for_high_overlap() -> None:
    gate = CompileQualityGate()

    result = gate.evaluate(
        CompileGeneratedInput(
            item_id="compile_suggestion:test:0001",
            doc_id="atom-test-0001",
            page_type="atom",
            topic="testing",
            problem_cluster="gate",
            content="# Test\n\n## Claims\n- raw-1\n- raw-2\n- raw-3\n\n## Evidence\n- raw-1\n- raw-2\n- raw-3",
            source_refs=["personal-1:raw-1", "personal-1:raw-2", "personal-1:raw-3"],
            summary="warning summary",
            confidence="medium",
        )
    )

    assert result["quality_status"] == "warning"
    assert result["increment_warning"] is True


def test_compile_quality_gate_passes_retrieval_ready_content() -> None:
    gate = CompileQualityGate()

    result = gate.evaluate(
        CompileGeneratedInput(
            item_id="compile_suggestion:test:0001",
            doc_id="atom-test-0001",
            page_type="atom",
            topic="testing",
            problem_cluster="gate",
            content="# Test\n\n## Claims\n- raw-1\n- raw-2\n\n## Evidence\n- concise synthesis with distinct wording",
            source_refs=["personal-1:raw-1", "personal-1:raw-2"],
            summary="pass summary",
            confidence="high",
        )
    )

    assert result["quality_status"] == "pass"
    assert result["critical_fact_coverage"] == 1.0
    assert result["source_ref_coverage"] == 1.0
