from pathlib import Path

import httpx

from agent_wiki.infrastructure.retrieval.embedding import SiliconFlowEmbeddingProvider


def test_siliconflow_embedding_provider_batches_requests(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            batch = calls[-1]["json"]["input"]
            return {
                "data": [
                    {"index": index, "embedding": [float(index), 0.5, 1.5]}
                    for index, _ in enumerate(batch)
                ]
            }

    def fake_post(url: str, *, headers: dict, json: dict, timeout: int):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    provider = SiliconFlowEmbeddingProvider(
        base_url="https://api.siliconflow.cn/v1",
        api_key_env="SILICONFLOW_API_KEY",
        model="BAAI/bge-m3",
        dimension=3,
        batch_size=2,
        timeout_seconds=30,
        http_post=fake_post,
    )

    embeddings = provider.embed_texts(["a", "b", "c"])

    assert len(calls) == 2
    assert calls[0]["url"] == "https://api.siliconflow.cn/v1/embeddings"
    assert calls[0]["json"]["model"] == "BAAI/bge-m3"
    assert calls[0]["json"]["input"] == ["a", "b"]
    assert calls[1]["json"]["input"] == ["c"]
    assert embeddings == [[0.0, 0.5, 1.5], [1.0, 0.5, 1.5], [0.0, 0.5, 1.5]]


def test_siliconflow_embedding_provider_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    provider = SiliconFlowEmbeddingProvider(
        base_url="https://api.siliconflow.cn/v1",
        api_key_env="SILICONFLOW_API_KEY",
        model="BAAI/bge-m3",
        dimension=3,
        batch_size=2,
        timeout_seconds=30,
        http_post=httpx.post,
    )

    try:
        provider.embed_texts(["missing key"])
    except ValueError as error:
        assert "SILICONFLOW_API_KEY" in str(error)
    else:
        raise AssertionError("expected missing api key failure")

