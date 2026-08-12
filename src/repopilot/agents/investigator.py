from __future__ import annotations

import re
from collections import Counter

from repopilot.models import Evidence, Finding, TaskState
from repopilot.tools.search_tools import CodeSearchTool, SearchRequest


class InvestigatorAgent:
    """Collects evidence only; it does not decide whether a claim is true."""

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

    def __init__(
        self,
        search_tool: CodeSearchTool,
        max_results_per_keyword: int = 30,
        context_lines: int = 3,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.search_tool = search_tool
        self.max_results_per_keyword = max_results_per_keyword
        self.context_lines = context_lines
        self.timeout_seconds = timeout_seconds

    def run(self, state: TaskState) -> TaskState:
        keywords = state.keywords or self._extract_keywords(state.question)
        state.keywords = keywords

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

    def _extract_keywords(self, question: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}|[\u4e00-\u9fff]{2,8}", question)
        unique: list[str] = []
        for token in tokens:
            if token.lower() in self.STOPWORDS or token in unique:
                continue
            unique.append(token)
        return unique[:6]
