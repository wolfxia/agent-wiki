import sys
import types

from agent_wiki.infrastructure.retrieval.tokenizer import BigramTokenizer, JiebaTokenizer, tokenize


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
