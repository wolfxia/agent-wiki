from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_wiki.extensions.embedding import OpenAICompatibleEmbeddingProvider, register_embedding_provider


class SiliconFlowEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
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


def _siliconflow_factory(*, config: Any, **kwargs: Any) -> SiliconFlowEmbeddingProvider:
    return SiliconFlowEmbeddingProvider(
        base_url=config.base_url,
        api_key_env=config.api_key_env,
        model=config.model,
        dimension=config.dimension,
        batch_size=config.batch_size,
        timeout_seconds=config.timeout_seconds,
        http_post=kwargs.get("http_post"),
    )


register_embedding_provider("siliconflow", _siliconflow_factory)
