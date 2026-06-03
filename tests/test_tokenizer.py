import sys
import types

from agent_wiki.infrastructure.retrieval.tokenizer import BigramTokenizer, JiebaTokenizer, _is_informative, tokenize


def test_bigram_tokenizer_remains_default() -> None:
    tokens = tokenize("Python部署策略")

    assert tokens == BigramTokenizer().tokenize("Python部署策略")
    assert "python" in tokens
    assert "部署" in tokens
    assert "策略" in tokens


def test_jieba_tokenizer_uses_jieba_when_available(monkeypatch) -> None:
    fake_jieba = types.SimpleNamespace(cut=lambda text: ["鸿蒙", "策略", "AOSP"])
    monkeypatch.setitem(sys.modules, "jieba", fake_jieba)

    tokens = JiebaTokenizer().tokenize("鸿蒙策略AOSP")

    assert tokens == ["鸿蒙", "策略", "aosp"]


def test_jieba_tokenizer_falls_back_to_bigram_when_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "jieba", None)

    tokens = JiebaTokenizer().tokenize("部署策略")

    assert tokens == BigramTokenizer().tokenize("部署策略")


def test_is_informative_filters_pure_single_digit() -> None:
    """P1-4: Single pure digits like "7" are not informative for retrieval."""
    assert not _is_informative("7")
    assert not _is_informative("42")
    assert _is_informative("2026")


def test_is_informative_filters_single_latin_chars() -> None:
    """P1-4: Single Latin chars (stop words like "a", "is") are filtered."""
    assert not _is_informative("a")
    assert not _is_informative("of")
    assert not _is_informative("is")
    assert _is_informative("ai")  # 2-letter acronym kept
    assert _is_informative("mcp")


def test_is_informative_filters_single_cjk_char() -> None:
    """P1-4: Single CJK characters are too ambiguous for retrieval."""
    assert not _is_informative("的")
    assert not _is_informative("一")
    assert _is_informative("鸿蒙")


def test_bigram_tokenizer_does_not_emit_single_digits() -> None:
    """P1-4: BigramTokenizer should not produce low-info terms like "7"."""
    tokens = BigramTokenizer().tokenize("Version 7 of the protocol")
    assert "7" not in tokens
    assert "version" in tokens
    assert "protocol" in tokens
