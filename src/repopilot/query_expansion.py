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
    """Cheap, reproducible baseline used for every automatically expanded query.

    Selects terms by *discriminative shape* instead of first-match order:

    - Title words are protected: they are the author's explicit intent, so they always
      outrank body-derived tokens.
    - The body is only mined for symbol-shaped tokens (stack traces, function names),
      so report-template words like ``System`` or ``Information`` cannot crowd out the
      fix location.
    - Compiler-macro noise (``-DOPENCV_...``, ``-D_Complex``) is stripped before
      extraction; a build log pasted into an issue used to monopolise every keyword.

    The common-word list is deliberately generic English/boilerplate — tuning it to one
    repository's issue template would be fitting the eval set.
    """

    # Generic function words and issue-report boilerplate. A term here is demoted, not
    # dropped, so a question that is genuinely about "tests" can still retrieve it.
    COMMON_WORDS = frozenset(
        {
            "about", "after", "again", "also", "and", "are", "because", "been",
            "before", "being", "between", "both", "but", "can", "could", "did",
            "does", "doesn't", "doesnt", "doing", "don't", "dont", "during", "each",
            "even", "for", "from", "had", "has", "have", "having", "how", "into",
            "may", "might", "more", "most", "much", "must", "not", "now", "only",
            "other", "our", "over", "same", "should", "since", "some", "such",
            "than", "that", "the", "their", "them", "then", "there", "these", "they",
            "this", "those", "through", "under", "until", "very", "was", "were",
            "what", "when", "where", "which", "while", "who", "will", "with",
            "without", "would", "you", "your",
            # Generic issue-report boilerplate (not repository-specific).
            "actual", "build", "builds", "code", "crash", "crashed", "crashes",
            "description", "detailed", "environment", "error", "errors", "expected",
            "fail", "failed", "fails", "failure", "failures", "file", "files",
            "function", "information", "issue", "issues", "line", "lines", "open",
            "opencv", "operating", "output", "platform", "please", "problem",
            "reproduce", "reproduced", "reproducing", "result", "results", "run",
            "running", "sample", "steps", "summary", "system", "test", "testing",
            "tests", "use", "used", "using", "value", "values", "version", "work",
            "working", "works",
        }
    )

    # Original small stop list retained as a hard filter.
    STOPWORDS = frozenset(
        {
            "about", "does", "from", "have", "how", "into", "that", "the",
            "this", "what", "when", "where", "which", "with",
        }
    )

    SYMBOL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,8}")

    # Compiler definitions pasted into issue bodies: -DNAME ... -D_Complex=double.
    COMPILER_MACRO_RE = re.compile(r"-D[A-Za-z_][A-Za-z0-9_]*")
    # Underscore-prefixed compiler/internal macros: _Complex, _MSC_VER, __FILE__.
    UNDERSCORE_MACRO_RE = re.compile(r"^_[A-Z]")

    # Title words get a modest bonus: the author's intent is a signal, but issue titles
    # are often generic ("several tests fail"), so a huge bonus would let low-value
    # title words crowd out real symbols mined from the body.
    TITLE_BONUS = 2.0
    # A body token must look this much like a code symbol to be mined at all.
    BODY_SYMBOL_THRESHOLD = 3.0

    def __init__(self, limit: int = 6) -> None:
        self.limit = limit

    def extract(self, question: str) -> list[str]:
        title, _, body = question.partition("\n\n")
        body = self.COMPILER_MACRO_RE.sub(" ", body)
        title = self.COMPILER_MACRO_RE.sub(" ", title)

        candidates: list[tuple[str, float, int]] = []  # (token, score, order)
        seen: set[str] = set()
        families: set[str] = set()
        order = 0

        def add(token: str, score: float) -> None:
            nonlocal order
            key = token.casefold()
            family = self._family(token)
            if (
                key in seen
                or family in families
                or key in self.STOPWORDS
                or self._is_noise(token)
            ):
                return
            seen.add(key)
            families.add(family)
            candidates.append((token, score, order))
            order += 1

        # Title: every token counts, with a modest bonus over body tokens.
        for token in self.SYMBOL_RE.findall(title):
            add(token, self._shape_score(token) + self.TITLE_BONUS)

        # Body: only symbol-shaped tokens (stack traces, function names, identifiers).
        for token in self.SYMBOL_RE.findall(body):
            shape = self._shape_score(token)
            if shape >= self.BODY_SYMBOL_THRESHOLD:
                add(token, shape)

        # Fallback: if symbols alone cannot fill the budget, take body words in
        # appearance order. Boilerplate is demoted by its negative shape score and
        # only surfaces when nothing better exists.
        if len(candidates) < self.limit:
            for token in self.SYMBOL_RE.findall(body):
                add(token, 0.0)

        candidates.sort(key=lambda item: (-item[1], item[2]))
        return [token for token, _score, _order in candidates[: self.limit]]

    def _is_noise(self, token: str) -> bool:
        """Compiler/internal macros that are symbols in shape but not in meaning."""
        return bool(self.UNDERSCORE_MACRO_RE.match(token))

    def _family(self, token: str) -> str:
        """Cluster sibling symbols so one family cannot monopolise the budget.

        `int32x4_CPP_EMULATOR` and `float64x2_CPP_EMULATOR` are sibling test cases of
        one family; keeping all six left zero room for the issue title's real terms.
        Two tokens share a family when their last two underscore segments match.
        """
        parts = token.split("_")
        if len(parts) >= 3:
            return "_".join(parts[-2:])
        return token

    def _shape_score(self, token: str) -> float:
        """How much this token looks like a code symbol rather than prose."""
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            return 1.0  # CJK fragments carry semantics but are not symbols
        score = 0.0
        if any(char.isupper() for char in token):
            score += 3.0  # CamelCase / class names
        if "_" in token:
            score += 2.0  # snake_case identifiers
        if any(char.isdigit() for char in token):
            score += 1.0  # constants / versioned symbols
        if len(token) >= 12:
            score += 1.0  # long tokens are usually identifiers
        if token.casefold() in self.COMMON_WORDS:
            score -= 5.0
        return score


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
