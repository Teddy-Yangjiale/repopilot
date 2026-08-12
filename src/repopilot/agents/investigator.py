from __future__ import annotations

from collections import Counter

from repopilot.models import (
    Evidence,
    Finding,
    QueryExpansionStrategy,
    QueryExpansionTrace,
    TaskState,
)
from repopilot.query_expansion import HybridQueryExpander
from repopilot.tools.search_tools import CodeSearchTool, SearchRequest


class InvestigatorAgent:
    """Collects evidence only; it does not decide whether a claim is true."""

    def __init__(
        self,
        search_tool: CodeSearchTool,
        query_expander: HybridQueryExpander | None = None,
        max_results_per_keyword: int = 30,
        context_lines: int = 3,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.search_tool = search_tool
        self.query_expander = query_expander or HybridQueryExpander()
        self.max_results_per_keyword = max_results_per_keyword
        self.context_lines = context_lines
        self.timeout_seconds = timeout_seconds

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

        all_evidence: list[Evidence] = []
        seen_locations: set[tuple[str, int, str]] = set()
        for keyword in keywords:
            results = self.search_tool.run(
                SearchRequest(
                    repo_path=state.repo_path,
                    keyword=keyword,
                    limit=self.max_results_per_keyword,
                    context_lines=self.context_lines,
                    timeout_seconds=self.timeout_seconds,
                )
            )
            for item in results:
                location = (item.path, item.line_start, item.snippet)
                if location not in seen_locations:
                    seen_locations.add(location)
                    all_evidence.append(item)

        state.evidence = all_evidence
        by_file = Counter(item.path for item in all_evidence)
        state.findings = [
            Finding(
                statement=f"{path} contains {count} relevant search hit(s).",
                evidence_ids=[item.id for item in all_evidence if item.path == path][:5],
                confidence=min(0.95, 0.55 + count * 0.05),
            )
            for path, count in by_file.most_common(8)
        ]
        if not all_evidence:
            state.findings = [
                Finding(
                    statement="No line-level evidence matched the selected keywords.",
                    confidence=1.0,
                )
            ]
        return state
