from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import httpx

from agent_wiki.application.compile_prepare import CompilePrepareResult
from agent_wiki.bootstrap.registry_loader import WikiConfig


class CompileApplyService:
    def __init__(self, http_post: Callable[..., Any] | None = None) -> None:
        self._http_post = http_post or httpx.post

    def generate(self, wiki: WikiConfig, prepare_result: CompilePrepareResult) -> str:
        llm = self._llm_config(wiki)
        if llm is None:
            raise ValueError("compile.llm config is required for --apply")
        api_key_env = self._config_value(llm, "api_key_env")
        api_key = os.environ.get(str(api_key_env))
        if not api_key:
            raise ValueError(f"missing LLM API key environment variable: {api_key_env}")

        prompt = self._build_prompt(prepare_result)
        response = self._http_post(
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
                            "Return only Markdown content for the page, no code fence."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": self._config_value(llm, "max_tokens", 4096),
                "temperature": 0.2,
            },
            timeout=self._config_value(llm, "timeout_seconds", 30),
        )
        response.raise_for_status()
        return self._extract_content(response.json())


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

    def _chat_completions_url(self, base_url: str) -> str:
        return base_url.rstrip("/") + "/chat/completions"

    def _build_prompt(self, prepare_result: CompilePrepareResult) -> str:
        payload = prepare_result.model_dump(mode="json")
        return (
            "Create one retrieval-ready atom page from this compile_prepare packet.\n"
            "The primary reader is an AI agent. Use concise structured Markdown.\n"
            "Include sections for Claims, Applicability, Evidence, Relationship Hints, and Open Questions when relevant.\n"
            "Preserve source refs exactly. Do not invent facts beyond the raw evidence.\n\n"
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
            raise ValueError("LLM returned empty content")
        return content

    def _strip_thinking(self, content: str) -> str:
        """Remove LLM thinking/reasoning blocks that leak into output.

        Some models (e.g. MiniMax M2.7) include <think>...</think> or
        raw thinking text before the actual answer. Strip these blocks
        and return only the content after the last closing tag.
        """
        import re
        # Remove blocks (may span multiple lines)
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        # Remove <<thinking>...</thinking> variant
        content = re.sub(r"<thinking>.*?</thinking>", "", content, flags=re.DOTALL).strip()
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
