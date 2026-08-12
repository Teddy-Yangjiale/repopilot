from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from repopilot.models import QueryExpansionStrategy, QueryExpansionTrace


class LLMConfigurationError(RuntimeError):
    """Raised when LLM mode was requested but cannot be configured."""


@dataclass(frozen=True)
class GeneratedKeywords:
    keywords: list[str]
    model: str
    latency_ms: int


class KeywordGenerator(Protocol):
    def generate(self, question: str) -> GeneratedKeywords: ...


@dataclass(frozen=True)
class ExpandedQuery:
    keywords: list[str]
    trace: QueryExpansionTrace


class DeterministicKeywordExtractor:
    """Cheap, reproducible baseline used for every automatically expanded query."""

    STOPWORDS = {
        "about",
        "does",
        "from",
        "have",
        "how",
        "into",
        "that",
        "the",
        "this",
        "what",
        "when",
        "where",
        "which",
        "with",
    }

    def __init__(self, limit: int = 6) -> None:
        self.limit = limit

    def extract(self, question: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}|[\u4e00-\u9fff]{2,8}", question)
        return self._deduplicate(tokens)[: self.limit]

    def _deduplicate(self, tokens: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            identity = token.casefold()
            if identity in self.STOPWORDS or identity in seen:
                continue
            seen.add(identity)
            unique.append(token)
        return unique


class HybridQueryExpander:
    """Merges deterministic recall with optional LLM-generated symbol candidates."""

    def __init__(
        self,
        generator: KeywordGenerator | None = None,
        extractor: DeterministicKeywordExtractor | None = None,
        limit: int = 10,
    ) -> None:
        self.generator = generator
        self.extractor = extractor or DeterministicKeywordExtractor()
        self.limit = limit

    def expand(self, question: str, use_llm: bool = False) -> ExpandedQuery:
        baseline = self.extractor.extract(question)
        if not use_llm:
            return ExpandedQuery(
                keywords=baseline,
                trace=QueryExpansionTrace(
                    strategy=QueryExpansionStrategy.DETERMINISTIC,
                    baseline_keywords=baseline,
                ),
            )

        if self.generator is None:
            raise LLMConfigurationError(
                "LLM query expansion is unavailable. Install the llm extra and configure .env."
            )

        try:
            generated = self.generator.generate(question)
        except LLMConfigurationError:
            raise
        except Exception as exc:
            warning = f"{type(exc).__name__}: {exc}"[:300]
            return ExpandedQuery(
                keywords=baseline,
                trace=QueryExpansionTrace(
                    strategy=QueryExpansionStrategy.HYBRID_FALLBACK,
                    baseline_keywords=baseline,
                    warning=warning,
                ),
            )

        llm_keywords = sanitize_keywords(generated.keywords)
        merged = merge_keywords(baseline, llm_keywords, self.limit)
        return ExpandedQuery(
            keywords=merged,
            trace=QueryExpansionTrace(
                strategy=QueryExpansionStrategy.HYBRID,
                baseline_keywords=baseline,
                llm_keywords=llm_keywords,
                model=generated.model,
                latency_ms=generated.latency_ms,
            ),
        )


def sanitize_keywords(values: list[str]) -> list[str]:
    """Treat model output as untrusted data before passing it to search tools."""

    cleaned: list[str] = []
    for value in values:
        candidate = value.strip().strip("`'\"")
        if 2 <= len(candidate) <= 80 and "\n" not in candidate and "\r" not in candidate:
            cleaned.append(candidate)
    return merge_keywords([], cleaned, len(cleaned))


def merge_keywords(baseline: list[str], generated: list[str], limit: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for keyword in [*baseline, *generated]:
        identity = keyword.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(keyword)
        if len(merged) == limit:
            break
    return merged


def parse_keyword_json(content: str) -> list[str]:
    """Parse a JSON object even when a model wraps it in a Markdown code fence."""

    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    payload = json.loads(content[start : end + 1])
    keywords = payload.get("keywords")
    if not isinstance(keywords, list) or not all(isinstance(item, str) for item in keywords):
        raise ValueError("LLM JSON must contain a string array named 'keywords'")
    return keywords
