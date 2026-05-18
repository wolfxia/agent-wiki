from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

from agent_wiki.application.compile_prepare import CompilePrepareResult
from agent_wiki.bootstrap.registry_loader import WikiConfig


class CompileStructuredOutput(BaseModel):
    content: str
    summary: str | None = None
    aliases: list[str] = Field(default_factory=list)
    confidence: str | None = None
    wikilinks: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    evidence_coverage: str | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty")
        return value.strip()


class CompileApplyService:
    def __init__(
        self,
        http_post: Callable[..., Any] | None = None,
        sleep: Callable[[int], Any] | None = None,
        max_retries: int | None = None,
        retry_delays: list[int] | None = None,
    ) -> None:
        self._http_post = http_post or httpx.post
        self._sleep = sleep or time.sleep
        self._max_retries_override = max_retries
        self._retry_delays_override = retry_delays
        self.last_attempts = 0
        self.last_usage: dict | None = None
        self.last_error_type: str | None = None
        self.last_structured_output: CompileStructuredOutput | None = None

    def generate(self, wiki: WikiConfig, prepare_result: CompilePrepareResult) -> str:
        llm = self._llm_config(wiki)
        if llm is None:
            raise ValueError("compile.llm config is required for --apply")
        api_key_env = self._config_value(llm, "api_key_env")
        api_key = os.environ.get(str(api_key_env))
        if not api_key:
            raise ValueError(f"missing LLM API key environment variable: {api_key_env}")

        max_retries = self._retry_config_value(llm, "max_retries", 3)
        retry_delays = self._retry_config_value(llm, "retry_delays", [10, 30, 60])
        prompt = self._build_prompt(prepare_result)
        self.last_usage = None
        self.last_error_type = None
        self.last_structured_output = None
        response = self._post_with_retries(
            self._chat_completions_url(str(self._config_value(llm, "base_url"))),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._config_value(llm, "model"),
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You compile raw evidence into an Agent Wiki atom page. "
                            "Return only valid JSON, no Markdown code fence and no prose outside JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": self._config_value(llm, "max_tokens", 4096),
                "temperature": 0.2,
            },
            timeout=self._config_value(llm, "timeout_seconds", 120),
            max_retries=max_retries,
            retry_delays=retry_delays,
        )
        response.raise_for_status()
        response_payload = response.json()
        usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
        self.last_usage = usage if isinstance(usage, dict) else None
        return self._extract_content(response_payload)


    def _post_with_retries(
        self,
        url: str,
        *,
        max_retries: int | None = None,
        retry_delays: list[int] | None = None,
        **kwargs: Any,
    ) -> Any:
        attempt = 0
        self.last_attempts = 0
        effective_max_retries = 3 if max_retries is None else max_retries
        effective_retry_delays = retry_delays or [10, 30, 60]
        while True:
            try:
                self.last_attempts = attempt + 1
                response = self._http_post(url, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, TimeoutError) as exc:
                self.last_error_type = "timeout"
                if not self._should_retry(attempt, effective_max_retries):
                    raise
                self._sleep_before_retry(attempt, effective_retry_delays)
                attempt += 1
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                self.last_error_type = "5xx" if status_code >= 500 else "4xx_auth"
                if status_code < 500 or not self._should_retry(attempt, effective_max_retries):
                    raise
                self._sleep_before_retry(attempt, effective_retry_delays)
                attempt += 1

    def _should_retry(self, attempt: int, max_retries: int) -> bool:
        return attempt < max_retries

    def _sleep_before_retry(self, attempt: int, retry_delays: list[int]) -> None:
        delay = retry_delays[min(attempt, len(retry_delays) - 1)]
        self._sleep(delay)


    def _llm_config(self, wiki: WikiConfig) -> Any | None:
        compile_config = getattr(wiki, "compile", None)
        if compile_config is None:
            return None
        if isinstance(compile_config, dict):
            return compile_config.get("llm")
        return getattr(compile_config, "llm", None)

    def _config_value(self, config: Any, key: str, default: Any | None = None) -> Any:
        if isinstance(config, dict):
            return config.get(key, default)
        return getattr(config, key, default)

    def _retry_config_value(self, config: Any, key: str, default: Any) -> Any:
        override = self._max_retries_override if key == "max_retries" else self._retry_delays_override
        if override is not None:
            return override
        return self._config_value(config, key, default)

    def _chat_completions_url(self, base_url: str) -> str:
        return base_url.rstrip("/") + "/chat/completions"

    def _build_prompt(self, prepare_result: CompilePrepareResult) -> str:
        payload = prepare_result.model_dump(mode="json")
        return (
            "Create one retrieval-ready atom page from this compile_prepare packet.\n"
            "The primary reader is an AI agent. Use concise structured Markdown.\n"
            "Include sections for Claims, Applicability, Evidence, Relationship Hints, and Open Questions when relevant.\n"
            "Preserve source refs exactly. Do not invent facts beyond the raw evidence.\n\n"
            "Return only valid JSON with this object shape:\n"
            "{\n"
            '  "content": "Markdown page body",\n'
            '  "summary": "one retrieval-ready sentence",\n'
            '  "aliases": ["alternate search phrase"],\n'
            '  "confidence": "low|medium|high",\n'
            '  "wikilinks": ["[[related-doc-id]]"],\n'
            '  "claims": ["atomic factual claim"],\n'
            '  "open_questions": ["unknown or weakly evidenced question"],\n'
            '  "evidence_coverage": "brief coverage note"\n'
            "}\n"
            "If you cannot provide an optional field, use null or an empty list.\n\n"
            f"compile_prepare_packet:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    def _extract_content(self, response_payload: dict) -> str:
        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("LLM response missing choices[0].message.content") from exc
        content = str(content).strip()
        content = self._strip_thinking(content)
        if content.startswith("```"):
            content = self._strip_code_fence(content)
        if not content:
            self.last_error_type = "invalid_output"
            raise ValueError("LLM returned empty content")
        structured = self._parse_structured_output(content)
        if structured is not None:
            self.last_structured_output = structured
            return structured.content
        return content

    def _parse_structured_output(self, content: str) -> CompileStructuredOutput | None:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return CompileStructuredOutput.model_validate(payload)
        except ValueError:
            return None

    def _strip_thinking(self, content: str) -> str:
        """Remove LLM thinking/reasoning blocks that leak into output.

        Some models include <think>...</think>, <reasoning_trace>...</reasoning_trace>,
        or raw thinking text before the actual answer. Strip these blocks and
        return only the content after the last closing tag.
        """
        import re
        thinking_tag = r"(?:think|thinking|reasoning|thought|reflection)[A-Za-z0-9_-]*"
        content = re.sub(
            rf"^[ \t]*<(?P<tag>{thinking_tag})\b[^>]*>.*?</(?P=tag)>[ \t]*(?:\r?\n)?",
            "",
            content,
            flags=re.DOTALL | re.IGNORECASE | re.MULTILINE,
        )
        content = re.sub(
            rf"<(?P<tag>{thinking_tag})\b[^>]*>.*?</(?P=tag)>",
            "",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()
        # If content starts with raw thinking (no tags), find first markdown heading
        # which typically marks the start of actual content
        lines = content.splitlines()
        first_heading = None
        for i, line in enumerate(lines):
            if line.startswith("#") and not line.startswith("#!") and not line.startswith("## "):
                # Skip lines inside code blocks
                first_heading = i
                break
            if line.startswith("## ") or line.startswith("# "):
                first_heading = i
                break
        if first_heading is not None and first_heading > 0:
            # Check if everything before the heading looks like thinking
            preamble = "\n".join(lines[:first_heading]).strip()
            if preamble and not preamble.startswith("#"):
                content = "\n".join(lines[first_heading:]).strip()
        return content

    def _strip_code_fence(self, content: str) -> str:
        lines = content.splitlines()
        if not lines or not lines[0].startswith("```"):
            return content.strip()
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        return "\n".join(lines).strip()
