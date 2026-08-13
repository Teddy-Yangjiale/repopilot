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
from repopilot.tools.search_tools import CodeSearchTool, SearchRequest, SearchResult


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

        state.evidence = self._deduplicate_evidence(results)
        state.ranked_files = self._rank(results, {item.id for item in state.evidence})
        state.findings = self._summarise(state)
        return state

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
