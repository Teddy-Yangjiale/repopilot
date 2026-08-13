from __future__ import annotations

from pathlib import Path

from repopilot.agents import InvestigatorAgent, PlannerAgent, VerifierAgent
from repopilot.models import TaskStage, TaskState
from repopilot.report import write_report
from repopilot.store import TaskStore
from repopilot.tools.git_tools import GitInspector
from repopilot.tools.path_policy import resolve_repo_root


class RepoPilotOrchestrator:
    """Explicit state transitions make retries, checkpoints and evaluation observable."""

    def __init__(
        self,
        investigator: InvestigatorAgent,
        planner: PlannerAgent,
        verifier: VerifierAgent,
        git_inspector: GitInspector,
        store: TaskStore,
        report_dir: Path,
    ) -> None:
        self.investigator = investigator
        self.planner = planner
        self.verifier = verifier
        self.git_inspector = git_inspector
        self.store = store
        self.report_dir = report_dir

    def create_task(
        self,
        repo_path: Path,
        question: str,
        keywords: list[str] | None = None,
        use_llm: bool = False,
    ) -> TaskState:
        root = resolve_repo_root(repo_path)
        state = TaskState(
            repo_path=root,
            question=question,
            keywords=keywords or [],
            use_llm=use_llm,
        )
        self.store.save(state)
        return state

    def run(self, state: TaskState) -> tuple[TaskState, Path]:
        try:
            if state.stage in (TaskStage.CREATED, TaskStage.INVESTIGATING):
                state.checkpoint(TaskStage.INVESTIGATING)
                self.store.save(state)
                state = self.investigator.run(state)
                state.checkpoint(TaskStage.PLANNING)
                self.store.save(state)

            if state.stage == TaskStage.PLANNING:
                state = self.planner.run(state)
                state.checkpoint(TaskStage.VERIFYING)
                self.store.save(state)

            if state.stage == TaskStage.VERIFYING:
                state = self.verifier.run(state)
                state.checkpoint(TaskStage.COMPLETED)
                self.store.save(state)

            snapshot = self.git_inspector.run(state.repo_path)
            report_path = write_report(state, snapshot, self.report_dir)
            return state, report_path
        except Exception as exc:
            state.error = f"{type(exc).__name__}: {exc}"
            state.checkpoint(TaskStage.FAILED)
            self.store.save(state)
            raise

    def resume(self, task_id: str) -> tuple[TaskState, Path]:
        state = self.store.load(task_id)
        if state.stage == TaskStage.COMPLETED:
            snapshot = self.git_inspector.run(state.repo_path)
            return state, write_report(state, snapshot, self.report_dir)
        if state.stage == TaskStage.FAILED:
            state.error = None
            state.checkpoint(TaskStage.INVESTIGATING)
        return self.run(state)
