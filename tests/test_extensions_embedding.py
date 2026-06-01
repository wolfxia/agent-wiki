from agent_wiki.bootstrap.registry_loader import EmbeddingConfig
from agent_wiki.extensions import (
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    create_embedding_provider,
    register_embedding_provider,
)


def test_openai_embedding_provider_uses_openai_compatible_embeddings_endpoint(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"index": 0, "embedding": [1, 2, 3]}]}

    def fake_post(url: str, *, headers: dict, json: dict, timeout: int):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    provider: EmbeddingProvider = OpenAIEmbeddingProvider(
        api_key_env="OPENAI_API_KEY",
        model="text-embedding-3-small",
        dimension=3,
        http_post=fake_post,
    )

    assert provider.embed_texts(["hello"]) == [[1.0, 2.0, 3.0]]
    assert calls[0]["url"] == "https://api.openai.com/v1/embeddings"
    assert calls[0]["headers"]["Authorization"] == "Bearer openai-key"
    assert calls[0]["json"] == {"model": "text-embedding-3-small", "input": ["hello"]}


def test_create_embedding_provider_selects_openai_from_config(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    config = EmbeddingConfig(
        provider="openai",
        api_key_env="OPENAI_API_KEY",
        model="text-embedding-3-small",
        dimension=1536,
    )

    provider = create_embedding_provider("openai", config)

    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.dimension == 1536


def test_create_embedding_provider_uses_registered_custom_provider() -> None:
    class CustomEmbeddingProvider:
        def __init__(self, config: EmbeddingConfig, **kwargs) -> None:
            self.config = config

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[float(len(text))] for text in texts]

    register_embedding_provider("knowledge-agent", CustomEmbeddingProvider)
    config = EmbeddingConfig(provider="knowledge-agent", api_key_env="IGNORED", model="custom")

    provider = create_embedding_provider("knowledge-agent", config)

    assert provider.embed_texts(["abc", "d"]) == [[3.0], [1.0]]


def test_create_embedding_provider_rejects_unknown_provider() -> None:
    config = EmbeddingConfig(provider="missing", api_key_env="IGNORED", model="missing")

    try:
        create_embedding_provider("missing", config)
    except ValueError as error:
        assert "unknown embedding provider" in str(error)
    else:
        raise AssertionError("expected unknown provider failure")
