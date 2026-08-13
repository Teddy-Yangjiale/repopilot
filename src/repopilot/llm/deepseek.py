"""OpenAI-compatible DeepSeek adapter, implemented with the standard library only.

No SDK dependency: the chat-completions protocol is small enough to speak directly,
which keeps the llm extra dependency-free and every failure path inspectable.

The generator keeps the narrow contract from `repopilot.query_expansion.KeywordGenerator`:
it turns a question into candidate search keywords and nothing else — no repository
path, file read or command execution authority.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from repopilot.query_expansion import (
    GeneratedKeywords,
    LLMConfigurationError,
    parse_keyword_json,
)


@dataclass(frozen=True)
class DeepSeekConfig:
    model: str
    api_key: str
    base_url: str
    timeout: int

    @classmethod
    def from_env(cls) -> DeepSeekConfig:
        api_key = os.getenv("LLM_API_KEY", "").strip()
        if not api_key or api_key == "your-deepseek-api-key":
            raise LLMConfigurationError(
                "LLM_API_KEY is missing. Copy .env.example to .env and add your DeepSeek key."
            )
        try:
            timeout = int(os.getenv("LLM_TIMEOUT", "120"))
        except ValueError as exc:
            raise LLMConfigurationError("LLM_TIMEOUT must be an integer number of seconds") from exc
        return cls(
            model=os.getenv("LLM_MODEL_ID", "deepseek-v4-flash"),
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            timeout=timeout,
        )


SYSTEM_PROMPT = (
    "You expand repository investigation queries. Return JSON only in the "
    'shape {"keywords":["..."]}. Produce at most 6 concise code symbols, '
    "class names, function names, filenames, or technical synonyms. Never "
    "return commands, paths outside the repository, or explanations."
)


class DeepSeekKeywordGenerator:
    """Narrow DeepSeek adapter: one structured call, no repository tool authority."""

    def __init__(self, config: DeepSeekConfig | None = None) -> None:
        # Injectable config makes the adapter unit-testable without environment setup.
        self._config = config

    def generate(self, question: str) -> GeneratedKeywords:
        config = self._config or DeepSeekConfig.from_env()
        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Generate search candidates for this question:\n"
                        f"<question>{question}</question>"
                    ),
                },
            ],
            "temperature": 0.0,
            "max_tokens": 300,
        }
        started = time.monotonic()
        data = self._post(config, payload)
        latency_ms = max(0, int((time.monotonic() - started) * 1000))

        choices = data.get("choices") or []
        message = choices[0].get("message") if choices else {}
        content = message.get("content") or ""
        return GeneratedKeywords(
            keywords=parse_keyword_json(content),
            model=data.get("model") or config.model,
            latency_ms=latency_ms,
        )

    def _post(self, config: DeepSeekConfig, payload: dict) -> dict:
        url = config.base_url.rstrip("/") + "/chat/completions"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise LLMConfigurationError(
                    "DeepSeek rejected the API key (HTTP 401). Check LLM_API_KEY."
                ) from exc
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {exc.reason}") from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"DeepSeek returned non-JSON: {raw[:200]!r}") from exc
