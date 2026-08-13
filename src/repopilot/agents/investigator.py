from __future__ import annotations

from repopilot.models import (
    Evidence,
    Finding,
    QueryExpansionStrategy,
    QueryExpansionTrace,
    TaskState,
)
from repopilot.query_expansion import HybridQueryExpander
from repopilot.ranking import DEFAULT_VENDORED_PENALTY, rank_files
from repopilot.symbols import enclosing_function
from repopilot.tools.search_tools import CodeSearchTool, SearchRequest, SearchResult

# Function names too generic to act as a discriminating symbol for caller recall.
_GENERIC_FUNCTION_NAMES = frozenset(
    {
        "main", "run", "init", "apply", "process", "handle", "get", "set",
        "test", "setup", "create", "parse", "build", "make", "call", "execute",
        "convert", "write", "read", "open", "close", "start", "stop",
    }
)


class InvestigatorAgent:
    """Collects evidence only; it does not decide whether a claim is true."""

    def __init__(
        self,
        search_tool: CodeSearchTool,
        query_expander: HybridQueryExpander | None = None,
        max_results_per_keyword: int = 30,
        context_lines: int = 3,
        timeout_seconds: float = 10.0,
        use_idf: bool = True,
        vendored_penalty: float = DEFAULT_VENDORED_PENALTY,
        use_length_norm: bool = False,
        # When True, the enclosing function names of hit lines are fed back into the
        # search as refined keywords, recalling callers via the text search. Off by
        # default and exposed for evaluation ablation.
        refine_symbols: bool = False,
        max_ranked_files: int = 50,
    ) -> None:
        self.search_tool = search_tool
        self.query_expander = query_expander or HybridQueryExpander()
        self.max_results_per_keyword = max_results_per_keyword
        self.context_lines = context_lines
        self.timeout_seconds = timeout_seconds
        # Exposed so the evaluation harness can ablate each ranking signal independently.
        self.use_idf = use_idf
        self.vendored_penalty = vendored_penalty
        self.use_length_norm = use_length_norm
        self.refine_symbols = refine_symbols
        # Every file matching any keyword is scored, but the tail is not worth persisting to
        # SQLite or returning over HTTP on every request.
        self.max_ranked_files = max_ranked_files

    def run(self, state: TaskState) -> TaskState:
        if state.keywords:
            keywords = state.keywords
            state.query_expansion = QueryExpansionTrace(
                strategy=QueryExpansionStrategy.EXPLICIT,
                baseline_keywords=keywords,
            )
        else:
            expanded = self.query_expander.expand(state.question, use_llm=state.use_llm)
            keywords = expanded.keywords
            state.keywords = keywords
            state.query_expansion = expanded.trace

        results: list[SearchResult] = [
            self.search_tool.run(
                SearchRequest(
                    repo_path=state.repo_path,
                    keyword=keyword,
                    limit=self.max_results_per_keyword,
                    context_lines=self.context_lines,
                    timeout_seconds=self.timeout_seconds,
                )
            )
            for keyword in keywords
        ]

        if self.refine_symbols:
            results = results + self._refine_symbols(state, results)

        state.evidence = self._deduplicate_evidence(results)
        state.ranked_files = self._rank(results, {item.id for item in state.evidence})
        state.findings = self._summarise(state)
        return state

    def _refine_symbols(self, state: TaskState, results: list[SearchResult]) -> list[SearchResult]:
        """Re-search the enclosing function names of top hit lines to recall callers.

        Calls `enclosing_function` on a bounded set of hit lines (top files by hit count,
        a few lines each), keeps non-generic names, and runs the ordinary text search on
        them. The names become additional SearchResults that flow through the exact same
        ranking, so the effect is one measurable signal, not a separate scoring path.
        """

        matched_files = sorted(
            (match for result in results for match in result.matches),
            key=lambda match: -len(match.hit_lines),
        )
        names: list[str] = []
        seen: set[str] = set()
        for match in matched_files[:10]:
            for line in match.hit_lines[:3]:
                function = enclosing_function(state.repo_path / match.path, line)
                if function is None or function.name in seen:
                    continue
                seen.add(function.name)
                if function.name not in _GENERIC_FUNCTION_NAMES and len(function.name) >= 5:
                    names.append(function.name)
            if len(names) >= 5:
                break

        return [
            self.search_tool.run(
                SearchRequest(
                    repo_path=state.repo_path,
                    keyword=name,
                    limit=self.max_results_per_keyword,
                    context_lines=self.context_lines,
                    timeout_seconds=self.timeout_seconds,
                )
            )
            for name in names
        ]

    def _deduplicate_evidence(self, results: list[SearchResult]) -> list[Evidence]:
        """The same keyword hitting the same line range is one piece of evidence.

        The key includes the keyword: without it, two search terms hitting the same
        region keep whichever arrived first, so the surviving evidence can claim a
        keyword that is absent from its cited lines — exactly what the verifier's
        re-read gate is designed to catch.
        """

        evidence: list[Evidence] = []
        seen: set[tuple[str, int, int, str]] = set()
        for result in results:
            for item in result.evidence:
                location = (item.path, item.line_start, item.line_end, item.keyword)
                if location not in seen:
                    seen.add(location)
                    evidence.append(item)
        return evidence

    def _rank(self, results: list[SearchResult], surviving_ids: set[str]):
        """Citations dropped by de-duplication must also drop out of the ranking, or the
        verifier would reject findings for referencing evidence that is no longer present."""

        ranked = rank_files(
            results,
            use_idf=self.use_idf,
            vendored_penalty=self.vendored_penalty,
            use_length_norm=self.use_length_norm,
        )[: self.max_ranked_files]
        for file in ranked:
            file.evidence_ids = [item for item in file.evidence_ids if item in surviving_ids]
        return ranked

    def _summarise(self, state: TaskState) -> list[Finding]:
        if not state.evidence:
            return [
                Finding(
                    statement="No line-level evidence matched the selected keywords.",
                    confidence=1.0,
                )
            ]
        return [
            Finding(
                statement=(
                    f"{file.path} matches {file.keyword_count} query term(s) "
                    f"across {file.evidence_count} location(s)."
                ),
                evidence_ids=file.evidence_ids[:5],
                confidence=min(0.95, 0.55 + file.keyword_count * 0.1),
            )
            for file in state.ranked_files[:8]
            if file.evidence_ids
        ]
