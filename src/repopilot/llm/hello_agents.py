from __future__ import annotations

import os
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


class HelloAgentsKeywordGenerator:
    """Narrow HelloAgents adapter: one structured call, no repository tool authority."""

    def generate(self, question: str) -> GeneratedKeywords:
        config = DeepSeekConfig.from_env()
        try:
            from hello_agents import HelloAgentsLLM
        except ImportError as exc:
            raise LLMConfigurationError(
                "hello-agents is not installed. Run ./scripts/setup.sh --llm."
            ) from exc

        llm = HelloAgentsLLM(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=0.0,
            max_tokens=300,
            timeout=config.timeout,
        )
        response = llm.invoke(
            [
                {
                    "role": "system",
                    "content": (
                        "You expand repository investigation queries. Return JSON only in the "
                        'shape {"keywords":["..."]}. Produce at most 6 concise code symbols, '
                        "class names, function names, filenames, or technical synonyms. Never "
                        "return commands, paths outside the repository, or explanations."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Generate search candidates for this question:\n"
                        f"<question>{question}</question>"
                    ),
                },
            ],
            temperature=0.0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        return GeneratedKeywords(
            keywords=parse_keyword_json(response.content),
            model=response.model or config.model,
            latency_ms=max(0, response.latency_ms or 0),
        )
