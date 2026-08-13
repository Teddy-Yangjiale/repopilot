from __future__ import annotations

from pathlib import Path

from repopilot.models import Evidence
from repopilot.runtime.context import ContextBuilder
from repopilot.runtime.models import (
    AgentDecision,
    AgentRun,
    AgentStep,
    AgentStepStatus,
    ContextPhase,
    ToolObservation,
)


def make_step(index: int, content: str, evidence: list[Evidence] | None = None) -> AgentStep:
    return AgentStep(
        index=index,
        decision=AgentDecision(
            tool_name="read_file",
            arguments={"path": f"src/file_{index}.py"},
            reason="inspect evidence",
        ),
        status=AgentStepStatus.SUCCEEDED,
        observation=ToolObservation(content=content, evidence=evidence or []),
        latency_ms=10,
    )


def test_decision_context_stays_within_budget_and_keeps_newest_steps() -> None:
    run = AgentRun(
        repo_path=Path("/tmp/repo"),
        question="How does the runtime work?",
        decision_context_chars=2_000,
        steps=[make_step(index, "x" * 1_500) for index in range(1, 7)],
    )

    context, trace = ContextBuilder().build_decision(run)

    indexes = [item["step"] for item in context["recent_history"]]
    assert trace.phase == ContextPhase.DECISION
    assert trace.chars_used <= trace.char_budget
    assert indexes == sorted(indexes)
    assert indexes[-1] == 6
    assert trace.steps_dropped > 0


def test_finalizer_prioritizes_read_evidence_and_deduplicates_ranges() -> None:
    search = Evidence(
        id="ev-search",
        path="src/agent.py",
        line_start=10,
        line_end=12,
        snippet="search result",
        keyword="AgentRuntime",
        source="local_code_search",
    )
    read = Evidence(
        id="ev-read",
        path="src/runtime.py",
        line_start=20,
        line_end=40,
        snippet="implementation " * 200,
        keyword="run",
        source="agent_read_file",
    )
    duplicate_read = read.model_copy(update={"id": "ev-read-duplicate"})
    run = AgentRun(
        repo_path=Path("/tmp/repo"),
        question="Explain the runtime",
        finalizer_context_chars=2_000,
        evidence=[search, read, duplicate_read],
    )

    context, trace = ContextBuilder().build_finalizer(run)

    included = [item["id"] for item in context["evidence"]]
    assert trace.phase == ContextPhase.FINALIZER
    assert trace.chars_used <= trace.char_budget
    assert included[0] == "ev-read-duplicate"
    assert "ev-read" not in included
    assert trace.evidence_dropped >= 1
    assert trace.step_indexes_included == []
    assert trace.steps_dropped == len(run.steps)


def test_long_question_is_truncated_instead_of_breaking_budget() -> None:
    run = AgentRun(
        repo_path=Path("/tmp/repo"),
        question="issue log " * 2_000,
        decision_context_chars=2_000,
    )

    context, trace = ContextBuilder().build_decision(run)

    assert trace.chars_used <= 2_000
    assert len(context["question"]) < len(run.question)
    assert trace.truncated_items == 1


def test_adversarial_evidence_fields_cannot_break_finalizer_budget() -> None:
    evidence = Evidence(
        id="ev-" + "i" * 2_000,
        path="nested/" + "p" * 4_000,
        line_start=1,
        line_end=2,
        snippet="s" * 10_000,
        keyword="k" * 2_000,
        source="source-" + "x" * 2_000,
    )
    run = AgentRun(
        repo_path=Path("/tmp/repo"),
        question="q" * 10_000,
        finalizer_context_chars=2_000,
        evidence=[evidence],
    )

    context, trace = ContextBuilder().build_finalizer(run)

    assert trace.chars_used <= trace.char_budget
    assert trace.truncated_items > 0
    assert len(context["evidence"]) == 1
