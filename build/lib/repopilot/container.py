from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from repopilot.agents import InvestigatorAgent, PlannerAgent, VerifierAgent
from repopilot.config import Settings
from repopilot.llm import DeepSeekKeywordGenerator
from repopilot.orchestrator import RepoPilotOrchestrator
from repopilot.query_expansion import HybridQueryExpander
from repopilot.store import TaskStore
from repopilot.tools import CodeSearchTool, GitInspector, SafeFileReader

# .env and the .repopilot state dir resolve against the current working directory
# (see config.Settings.resolve_state_dir), so both pip and editable installs behave.


@lru_cache(maxsize=1)
def get_orchestrator() -> RepoPilotOrchestrator:
    load_dotenv(Path.cwd() / ".env", override=False)
    settings = Settings()
    state_dir = settings.resolve_state_dir()
    investigator = InvestigatorAgent(
        search_tool=CodeSearchTool(),
        query_expander=HybridQueryExpander(generator=DeepSeekKeywordGenerator()),
        max_results_per_keyword=settings.max_search_results,
        context_lines=settings.context_lines,
        timeout_seconds=settings.search_timeout_seconds,
    )
    return RepoPilotOrchestrator(
        investigator=investigator,
        planner=PlannerAgent(),
        verifier=VerifierAgent(reader=SafeFileReader(max_file_bytes=settings.max_file_bytes)),
        git_inspector=GitInspector(),
        store=TaskStore(state_dir / "tasks.db"),
        report_dir=state_dir / "reports",
    )
