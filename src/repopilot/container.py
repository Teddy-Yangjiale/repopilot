from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from repopilot.agents import InvestigatorAgent, PlannerAgent, VerifierAgent
from repopilot.config import Settings
from repopilot.orchestrator import RepoPilotOrchestrator
from repopilot.store import TaskStore
from repopilot.tools import CodeSearchTool, GitInspector

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def get_orchestrator() -> RepoPilotOrchestrator:
    settings = Settings()
    state_dir = settings.resolve_state_dir(PROJECT_ROOT)
    investigator = InvestigatorAgent(
        search_tool=CodeSearchTool(),
        max_results_per_keyword=settings.max_search_results,
        context_lines=settings.context_lines,
        timeout_seconds=settings.search_timeout_seconds,
    )
    return RepoPilotOrchestrator(
        investigator=investigator,
        planner=PlannerAgent(),
        verifier=VerifierAgent(),
        git_inspector=GitInspector(),
        store=TaskStore(state_dir / "tasks.db"),
        report_dir=state_dir / "reports",
    )
