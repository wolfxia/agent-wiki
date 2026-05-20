from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import httpx


class SiliconFlowEmbeddingProvider:
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
