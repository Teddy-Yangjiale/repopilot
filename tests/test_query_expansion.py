from __future__ import annotations

from dataclasses import dataclass

import pytest

from repopilot.models import QueryExpansionStrategy
from repopilot.query_expansion import (
    GeneratedKeywords,
    HybridQueryExpander,
    LLMConfigurationError,
    parse_keyword_json,
)


@dataclass
class FakeGenerator:
    result: GeneratedKeywords | None = None
    error: Exception | None = None
    calls: int = 0

    def generate(self, question: str) -> GeneratedKeywords:
        self.calls += 1
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


def test_deterministic_mode_never_calls_llm() -> None:
    generator = FakeGenerator(error=AssertionError("LLM should not be called"))
    expanded = HybridQueryExpander(generator=generator).expand(
        "How does ReActAgent execute invoke_with_tools?",
        use_llm=False,
    )

    assert expanded.trace.strategy == QueryExpansionStrategy.DETERMINISTIC
    assert expanded.keywords == ["ReActAgent", "execute", "invoke_with_tools"]
    assert generator.calls == 0


def test_hybrid_mode_merges_and_sanitizes_model_candidates() -> None:
    generator = FakeGenerator(
        result=GeneratedKeywords(
            keywords=["reactagent", " ToolRegistry ", "`Finish`", "bad\ncommand"],
            model="fake-deepseek",
            latency_ms=42,
        )
    )
    expanded = HybridQueryExpander(generator=generator).expand(
        "How does ReActAgent stop?",
        use_llm=True,
    )

    assert expanded.keywords == ["ReActAgent", "stop", "ToolRegistry", "Finish"]
    assert expanded.trace.strategy == QueryExpansionStrategy.HYBRID
    assert expanded.trace.llm_keywords == ["reactagent", "ToolRegistry", "Finish"]
    assert expanded.trace.model == "fake-deepseek"
    assert expanded.trace.latency_ms == 42


def test_runtime_failure_falls_back_to_reproducible_baseline() -> None:
    expanded = HybridQueryExpander(
        generator=FakeGenerator(error=TimeoutError("provider timed out"))
    ).expand("Where is ReActAgent implemented?", use_llm=True)

    assert expanded.keywords == ["ReActAgent", "implemented"]
    assert expanded.trace.strategy == QueryExpansionStrategy.HYBRID_FALLBACK
    assert expanded.trace.warning == "TimeoutError: provider timed out"


def test_configuration_errors_are_not_silently_hidden() -> None:
    with pytest.raises(LLMConfigurationError, match="configure .env"):
        HybridQueryExpander().expand("Where is ReActAgent?", use_llm=True)


def test_json_parser_accepts_fenced_object_and_rejects_wrong_schema() -> None:
    assert parse_keyword_json('```json\n{"keywords":["ReActAgent"]}\n```') == ["ReActAgent"]
    with pytest.raises(ValueError, match="string array"):
        parse_keyword_json('{"keywords":"ReActAgent"}')
