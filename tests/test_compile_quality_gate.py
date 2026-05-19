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


def test_compile_quality_gate_covers_chinese_content_with_doc_id_substring() -> None:
    gate = CompileQualityGate()

    result = gate.evaluate(
        CompileGeneratedInput(
            item_id="compile_suggestion:test:0001",
            doc_id="atom-agent-os-scheduling",
            page_type="atom",
            topic="agent-os",
            problem_cluster="调度",
            content=(
                "# Agent OS 调度\n\n"
                "## Claims\n"
                "- 这条中文总结来自 agent-os_2026-05-03-agent-scheduling-notes。\n\n"
                "## Evidence\n"
                "- source_ref 保留为 agent-os_2026-05-03-agent-scheduling-notes。"
            ),
            source_refs=["personal-1:agent-os_2026-05-03-agent-scheduling-notes"],
            summary="中文调度总结。",
            confidence="high",
        )
    )

    assert result["critical_fact_coverage"] == 1.0


def test_compile_quality_gate_covers_mixed_chinese_doc_id_by_bigram_overlap() -> None:
    gate = CompileQualityGate()

    result = gate.evaluate(
        CompileGeneratedInput(
            item_id="compile_suggestion:test:0001",
            doc_id="atom-chinese-mixed",
            page_type="atom",
            topic="agent-os",
            problem_cluster="调度",
            content=(
                "# 中文混合来源\n\n"
                "## Claims\n"
                "- 该结论覆盖 智能体调度 的上下文，并保留 agent-os 主题。\n\n"
                "## Evidence\n"
                "- 原始资料讨论智能体调度策略。"
            ),
            source_refs=["personal-1:智能体调度-agent-os-notes"],
            summary="智能体调度总结。",
            confidence="high",
        )
    )

    assert result["critical_fact_coverage"] == 1.0
