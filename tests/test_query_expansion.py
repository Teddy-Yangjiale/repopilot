from __future__ import annotations

from dataclasses import dataclass

import pytest

from repopilot.models import QueryExpansionStrategy
from repopilot.query_expansion import (
    DeterministicKeywordExtractor,
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
    # Symbols outrank ordinary verbs: invoke_with_tools before execute.
    assert expanded.keywords == ["ReActAgent", "invoke_with_tools", "execute"]
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


def test_extractor_prefers_symbols_over_issue_template_boilerplate() -> None:
    """The stage-A failure: `System Information` template words crowding out the real symbol."""
    question = (
        "Pointer overflow in icvCvt_BGRA2RGBA_16u_C4R when decoding\n\n"
        "System Information\n"
        "OpenCV version 4.x\n"
        "Detailed description: crash in TiffDecoder::readData"
    )
    keywords = DeterministicKeywordExtractor().extract(question)

    assert keywords[0] == "icvCvt_BGRA2RGBA_16u_C4R"
    assert "System" not in keywords
    assert "Information" not in keywords
    assert "OpenCV" not in keywords


def test_extractor_mines_symbols_from_body_stack_trace() -> None:
    """Body tokens that look like code symbols are mined even past template words."""
    question = (
        "Crash while decoding\n\n"
        "System Information\n"
        "Stack:\n"
        "  icvCvt_BGRA2RGBA_16u_C4R (utils.cpp:241)\n"
        "  TiffDecoder::readData (grfmt_tiff.cpp:1085)"
    )
    keywords = DeterministicKeywordExtractor().extract(question)

    assert "TiffDecoder" in keywords
    assert "icvCvt_BGRA2RGBA_16u_C4R" in keywords
    assert "System" not in keywords


def test_extractor_filters_compiler_macros_from_build_logs() -> None:
    """Build-log `-D` macros used to monopolise every keyword slot (zero-evidence case)."""
    question = (
        "Several tests fail in core\n\n"
        "Build command:\n"
        "-DOPENCV_ALLOCATOR_STATS_COUNTER_TYPE=long -DCVAPI_EXPORTS -D_Complex=double\n"
        "stack: modules/core/src/hal_internal.cpp:123"
    )
    keywords = DeterministicKeywordExtractor().extract(question)

    assert not any(
        kw.startswith("DOPENCV") or kw.startswith("DCVAPI") or kw == "_Complex"
        for kw in keywords
    )
    assert "hal_internal" in keywords
