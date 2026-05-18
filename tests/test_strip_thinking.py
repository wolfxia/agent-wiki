"""Tests for _strip_thinking that removes LLM thinking block leakage."""
from agent_wiki.application.compile_apply import CompileApplyService


def _service() -> CompileApplyService:
    return CompileApplyService()


def test_raw_thinking_before_heading_stripped() -> None:
    content = "Let me analyze...\nI need to create a page.\n\n# Title\nBody"
    result = _service()._strip_thinking(content)
    assert result.startswith("# Title")


def test_clean_content_preserved() -> None:
    content = "# Title\nBody"
    result = _service()._strip_thinking(content)
    assert result == "# Title\nBody"


def test_thinking_tag_variant_stripped() -> None:
    tag_open = "<" + "thinking>"
    tag_close = "</" + "thinking>"
    content = f"{tag_open}internal reasoning{tag_close}\n\n# Title\nBody"
    result = _service()._strip_thinking(content)
    assert result.startswith("# Title")


def test_multiple_thinking_blocks() -> None:
    tag_open = "<" + "thinking>"
    tag_close = "</" + "thinking>"
    content = f"{tag_open}first{tag_close}\nmiddle{tag_open}second{tag_close}\n\n# Title\nBody"
    result = _service()._strip_thinking(content)
    assert result.startswith("# Title")


def test_thinking_with_multiline_content() -> None:
    tag_open = "<" + "thinking>"
    tag_close = "</" + "thinking>"
    content = f"{tag_open}\nline1\nline2\n{tag_close}\n\n# Title\nBody"
    result = _service()._strip_thinking(content)
    assert result.startswith("# Title")
