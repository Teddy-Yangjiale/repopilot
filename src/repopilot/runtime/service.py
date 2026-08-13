from __future__ import annotations

from pathlib import Path

from repopilot.runtime.engine import AgentRuntime
from repopilot.runtime.models import AgentRun
from repopilot.runtime.policy import DecisionPolicy
from repopilot.runtime.report import write_agent_report
from repopilot.runtime.store import AgentRunStore
from repopilot.runtime.tooling import ToolRegistry
from repopilot.tools.path_policy import resolve_repo_root


class AgentService:
    """Application boundary: creation, durable execution, resumption and reporting."""

    def __init__(
        self,
        policy: DecisionPolicy,
        store: AgentRunStore,
        report_dir: Path,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.store = store
        self.report_dir = report_dir
        self.runtime = AgentRuntime(
            policy=policy,
            tools=tools or ToolRegistry.readonly_default(),
            checkpoint=store.save,
        )

    def create(
        self,
        repo_path: Path,
        question: str,
        max_steps: int = 8,
        timeout_seconds: float = 120,
    ) -> AgentRun:
        run = AgentRun(
            repo_path=resolve_repo_root(repo_path),
            question=question,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
        )
        self.store.save(run)
        return run

    def execute(self, run: AgentRun) -> tuple[AgentRun, Path]:
        run = self.runtime.run(run)
        return run, write_agent_report(run, self.report_dir)

    def resume(self, run_id: str) -> tuple[AgentRun, Path]:
        return self.execute(self.store.load(run_id))
