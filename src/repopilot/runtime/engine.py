from __future__ import annotations

import subprocess
import time
from collections.abc import Callable

from repopilot.runtime.models import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    ToolObservation,
)
from repopilot.runtime.policy import DecisionPolicy
from repopilot.runtime.tooling import FinishArguments, ToolExecutionError, ToolRegistry

Checkpoint = Callable[[AgentRun], None]


class AgentRuntime:
    """A bounded Plan-Act-Observe loop with a checkpoint after every environment action."""

    def __init__(
        self,
        policy: DecisionPolicy,
        tools: ToolRegistry,
        checkpoint: Checkpoint | None = None,
    ) -> None:
        self.policy = policy
        self.tools = tools
        self.checkpoint = checkpoint or (lambda run: None)

    def run(self, run: AgentRun) -> AgentRun:
        if run.status == AgentRunStatus.COMPLETED:
            return run
        run.status = AgentRunStatus.RUNNING
        run.error = None
        self.checkpoint(run)
        started = time.monotonic()

        try:
            while len(run.steps) < run.max_steps:
                if time.monotonic() - started >= run.timeout_seconds:
                    run.status = AgentRunStatus.BUDGET_EXHAUSTED
                    run.error = "time budget exhausted"
                    self.checkpoint(run)
                    return run

                step_started = time.monotonic()
                decision = self.policy.decide(run, self.tools.schemas)
                status = AgentStepStatus.SUCCEEDED
                try:
                    self.tools.validate(decision.tool_name, decision.arguments)
                    self._reject_duplicate(run, decision.tool_name, decision.arguments)
                    self._validate_read_target(run, decision.tool_name, decision.arguments)
                    observation = self.tools.execute(
                        decision.tool_name, run.repo_path, decision.arguments
                    )
                    if decision.tool_name == "finish":
                        self._finish(run, decision.arguments, observation)
                except (
                    ToolExecutionError,
                    ValueError,
                    OSError,
                    subprocess.SubprocessError,
                ) as exc:
                    status = AgentStepStatus.TOOL_ERROR
                    observation = ToolObservation(content=f"{type(exc).__name__}: {exc}"[:2000])

                step = AgentStep(
                    index=len(run.steps) + 1,
                    decision=decision,
                    status=status,
                    observation=observation,
                    latency_ms=max(0, int((time.monotonic() - step_started) * 1000)),
                )
                run.steps.append(step)
                self._merge_evidence(run, observation)
                self.checkpoint(run)
                if run.status == AgentRunStatus.COMPLETED:
                    return run

            run.status = AgentRunStatus.BUDGET_EXHAUSTED
            run.error = f"step budget exhausted after {run.max_steps} actions"
            self.checkpoint(run)
            return run
        except Exception as exc:
            run.status = AgentRunStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"[:1000]
            self.checkpoint(run)
            raise

    def _reject_duplicate(
        self, run: AgentRun, tool_name: str, arguments: dict[str, object]
    ) -> None:
        fingerprint = self.tools.fingerprint(tool_name, arguments)
        previous = {
            self.tools.fingerprint(step.decision.tool_name, step.decision.arguments)
            for step in run.steps
        }
        if fingerprint in previous:
            raise ToolExecutionError("duplicate action rejected; choose a different next step")

    def _validate_read_target(
        self, run: AgentRun, tool_name: str, arguments: dict[str, object]
    ) -> None:
        if tool_name != "read_file":
            return
        path = str(arguments.get("path") or "")
        discovered_paths = {
            str(path)
            for step in run.steps
            if step.decision.tool_name == "search_code"
            and step.status == AgentStepStatus.SUCCEEDED
            for path in step.observation.metadata.get("paths", [])
        }
        if path not in discovered_paths:
            raise ToolExecutionError(
                f"read_file path {path!r} was not discovered by search_code in this run"
            )

    def _finish(
        self,
        run: AgentRun,
        raw_arguments: dict[str, object],
        observation: ToolObservation,
    ) -> None:
        arguments = FinishArguments.model_validate(raw_arguments)
        known = {item.id for item in run.evidence}
        cited = set(arguments.evidence_ids)
        missing = cited - known
        if missing:
            raise ToolExecutionError(
                f"finish cited unknown evidence IDs: {', '.join(sorted(missing))}"
            )
        run.final_answer = observation.content
        run.final_claims = arguments.claims
        run.final_evidence_ids = arguments.evidence_ids
        run.status = AgentRunStatus.COMPLETED

    def _merge_evidence(self, run: AgentRun, observation: ToolObservation) -> None:
        known = {item.id for item in run.evidence}
        for item in observation.evidence:
            if item.id not in known:
                known.add(item.id)
                run.evidence.append(item)
