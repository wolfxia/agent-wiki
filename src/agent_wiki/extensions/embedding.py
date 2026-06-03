from __future__ import annotations

import os
from collections.abc import Callable
from importlib import import_module, metadata
from typing import Any, Protocol, runtime_checkable

import httpx


@runtime_checkable
class EmbeddingProvider(Protocol):
    dimension: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key_env: str,
        model: str,
        dimension: int,
        batch_size: int = 32,
        timeout_seconds: int = 30,
        http_post: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.model = model
        self.dimension = dimension
        self.batch_size = max(int(batch_size), 1)
        self.timeout_seconds = timeout_seconds
        self._http_post = http_post or httpx.post

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ValueError(f"missing embedding API key environment variable: {self.api_key_env}")

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            response = self._http_post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": batch},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise ValueError("embedding response missing data list")
            ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
            for item in ordered:
                embedding = item.get("embedding")
                if not isinstance(embedding, list):
                    raise ValueError("embedding response missing embedding vector")
                embeddings.append([float(value) for value in embedding])
        return embeddings


class OpenAIEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
    def __init__(
        self,
        *,
        api_key_env: str,
        model: str,
        dimension: int,
        base_url: str = "https://api.openai.com/v1",
        batch_size: int = 32,
        timeout_seconds: int = 30,
        http_post: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key_env=api_key_env,
            model=model,
            dimension=dimension,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
            http_post=http_post,
        )


class AzureOpenAIEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key_env: str,
        model: str,
        dimension: int,
        batch_size: int = 32,
        timeout_seconds: int = 30,
        http_post: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key_env=api_key_env,
            model=model,
            dimension=dimension,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
            http_post=http_post,
        )


EmbeddingProviderFactory = Callable[..., EmbeddingProvider]

_EMBEDDING_PROVIDER_REGISTRY: dict[str, EmbeddingProviderFactory] = {}


def register_embedding_provider(provider_type: str, factory: EmbeddingProviderFactory) -> None:
    normalized = provider_type.strip().lower()
    if not normalized:
        raise ValueError("embedding provider type must not be empty")
    _EMBEDDING_PROVIDER_REGISTRY[normalized] = factory


def create_embedding_provider(provider_type: str, config: Any, **kwargs: Any) -> EmbeddingProvider:
    normalized = provider_type.strip().lower()
    _load_configured_provider_modules(config)
    factory = _EMBEDDING_PROVIDER_REGISTRY.get(normalized)
    if factory is None:
        _load_entry_point_provider(normalized)
        factory = _EMBEDDING_PROVIDER_REGISTRY.get(normalized)
    if factory is None:
        raise ValueError(f"unknown embedding provider: {provider_type}")
    return factory(config=config, **kwargs)


def _load_configured_provider_modules(config: Any) -> None:
    modules: list[str] = []
    provider_module = getattr(config, "provider_module", None)
    if provider_module:
        modules.append(str(provider_module))
    modules.extend(str(module) for module in getattr(config, "provider_modules", []) or [] if str(module).strip())
    env_modules = os.environ.get("AGENT_WIKI_EMBEDDING_PROVIDER_MODULES", "")
    modules.extend(module.strip() for module in env_modules.split(",") if module.strip())
    for module_name in dict.fromkeys(modules):
        import_module(module_name)


def _load_entry_point_provider(provider_type: str) -> None:
    try:
        entry_points = metadata.entry_points(group="agent_wiki.embedding_providers")
    except TypeError:
        entry_points = metadata.entry_points().get("agent_wiki.embedding_providers", ())
    for entry_point in entry_points:
        if entry_point.name.strip().lower() == provider_type:
            entry_point.load()
            return


def _openai_factory(*, config: Any, **kwargs: Any) -> EmbeddingProvider:
    return OpenAIEmbeddingProvider(
        base_url=getattr(config, "base_url", None) or "https://api.openai.com/v1",
        api_key_env=config.api_key_env,
        model=config.model,
        dimension=config.dimension,
        batch_size=config.batch_size,
        timeout_seconds=config.timeout_seconds,
        http_post=kwargs.get("http_post"),
    )


def _azure_openai_factory(*, config: Any, **kwargs: Any) -> EmbeddingProvider:
    return AzureOpenAIEmbeddingProvider(
        base_url=config.base_url,
        api_key_env=config.api_key_env,
        model=config.model,
        dimension=config.dimension,
        batch_size=config.batch_size,
        timeout_seconds=config.timeout_seconds,
        http_post=kwargs.get("http_post"),
    )


register_embedding_provider("openai", _openai_factory)
register_embedding_provider("azure_openai", _azure_openai_factory)
