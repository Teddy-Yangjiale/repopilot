from pathlib import Path

from repopilot.models import Evidence
from repopilot.runtime.models import (
    AgentDecision,
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    ToolObservation,
)
from repopilot.runtime.store import AgentRunStore


def test_context_replay_uses_persisted_trajectory_without_model(tmp_path: Path) -> None:
    from repopilot.eval.context_replay import replay_contexts

    evidence = Evidence(
        path="src/runtime.py",
        line_start=10,
        line_end=20,
        snippet="runtime implementation " * 100,
        keyword="runtime",
        source="agent_read_file",
    )
    run = AgentRun(
        repo_path=tmp_path,
        question="How does the runtime work?",
        max_steps=2,
        status=AgentRunStatus.COMPLETED,
        steps=[
            AgentStep(
                index=1,
                decision=AgentDecision(tool_name="read_file", arguments={}),
                status=AgentStepStatus.SUCCEEDED,
                observation=ToolObservation(content="x" * 4_000, evidence=[evidence]),
                latency_ms=1,
            ),
            AgentStep(
                index=2,
                decision=AgentDecision(tool_name="finish", arguments={}),
                status=AgentStepStatus.SUCCEEDED,
                observation=ToolObservation(content="done"),
                latency_ms=1,
            ),
        ],
        evidence=[evidence],
    )
    database = tmp_path / "agent_eval.db"
    AgentRunStore(database).save(run)

    metrics = replay_contexts(database, 2_000, 2_000)

    assert metrics["runs"] == 1
    assert metrics["decision_calls"] == 1
    assert metrics["finalizer_calls"] == 1
    assert metrics["new_decision_chars_max"] <= 2_000
    assert metrics["new_finalizer_chars_max"] <= 2_000
