from __future__ import annotations

from pathlib import Path

import pytest

from repopilot.runtime.models import AgentDecision, AgentRun, AgentRunStatus, AgentStepStatus
from repopilot.runtime.service import AgentService
from repopilot.runtime.store import AgentRunStore


class SearchThenFinishPolicy:
    def decide(self, run: AgentRun, tool_schemas: list[dict]) -> AgentDecision:
        if not run.steps:
            return AgentDecision(
                tool_name="search_code",
                arguments={"keyword": "ReActAgent", "reason": "locate the class"},
                reason="locate the class",
            )
        return AgentDecision(
            tool_name="finish",
            arguments={
                "answer": "ReActAgent is defined at the cited source location and stops on Finish.",
                "evidence_ids": [run.evidence[0].id],
                "reason": "the source evidence is sufficient",
            },
            reason="the source evidence is sufficient",
        )


class RepeatSearchPolicy:
    def decide(self, run: AgentRun, tool_schemas: list[dict]) -> AgentDecision:
        return AgentDecision(
            tool_name="search_code",
            arguments={"keyword": "ReActAgent", "reason": "repeat"},
            reason="repeat",
        )


class ForgedFinishPolicy:
    def decide(self, run: AgentRun, tool_schemas: list[dict]) -> AgentDecision:
        return AgentDecision(
            tool_name="finish",
            arguments={
                "answer": "This answer is long enough but cites evidence that was never collected.",
                "evidence_ids": ["ev-invented"],
                "reason": "attempt to finish",
            },
            reason="attempt to finish",
        )


class FailAfterSearchPolicy(SearchThenFinishPolicy):
    def decide(self, run: AgentRun, tool_schemas: list[dict]) -> AgentDecision:
        if run.steps:
            raise RuntimeError("simulated model outage")
        return super().decide(run, tool_schemas)


class InvalidReadPolicy:
    def __init__(self, arguments: dict[str, object]) -> None:
        self.arguments = arguments

    def decide(self, run: AgentRun, tool_schemas: list[dict]) -> AgentDecision:
        return AgentDecision(
            tool_name="read_file",
            arguments=self.arguments,
            reason="exercise the tool boundary",
        )


def build_service(tmp_path: Path, policy) -> AgentService:
    return AgentService(
        policy=policy,
        store=AgentRunStore(tmp_path / "state" / "agent_runs.db"),
        report_dir=tmp_path / "state" / "agent_reports",
    )


def test_plan_act_observe_run_finishes_with_real_evidence(
    sample_repo: Path, tmp_path: Path
) -> None:
    service = build_service(tmp_path, SearchThenFinishPolicy())
    run = service.create(sample_repo, "How does ReActAgent stop?")
    completed, report = service.execute(run)

    assert completed.status == AgentRunStatus.COMPLETED
    assert [step.decision.tool_name for step in completed.steps] == ["search_code", "finish"]
    assert completed.final_evidence_ids == [completed.evidence[0].id]
    assert completed.total_tokens == 0
    assert report.exists()
    assert "Action / Observation trajectory" in report.read_text(encoding="utf-8")


def test_duplicate_action_is_an_observation_and_consumes_budget(
    sample_repo: Path, tmp_path: Path
) -> None:
    service = build_service(tmp_path, RepeatSearchPolicy())
    run = service.create(sample_repo, "Where is ReActAgent?", max_steps=2)
    completed, _ = service.execute(run)

    assert completed.status == AgentRunStatus.BUDGET_EXHAUSTED
    assert completed.steps[0].status == AgentStepStatus.SUCCEEDED
    assert completed.steps[1].status == AgentStepStatus.TOOL_ERROR
    assert "duplicate action rejected" in completed.steps[1].observation.content


def test_finish_rejects_unknown_evidence_ids(sample_repo: Path, tmp_path: Path) -> None:
    service = build_service(tmp_path, ForgedFinishPolicy())
    run = service.create(sample_repo, "Where is ReActAgent?", max_steps=1)
    completed, _ = service.execute(run)

    assert completed.status == AgentRunStatus.BUDGET_EXHAUSTED
    assert completed.final_answer is None
    assert completed.steps[0].status == AgentStepStatus.TOOL_ERROR
    assert "unknown evidence IDs" in completed.steps[0].observation.content


def test_failed_run_resumes_without_repeating_completed_search(
    sample_repo: Path, tmp_path: Path
) -> None:
    failed_service = build_service(tmp_path, FailAfterSearchPolicy())
    run = failed_service.create(sample_repo, "How does ReActAgent stop?")
    with pytest.raises(RuntimeError, match="simulated model outage"):
        failed_service.execute(run)

    persisted = failed_service.store.load(run.run_id)
    assert persisted.status == AgentRunStatus.FAILED
    assert len(persisted.steps) == 1

    resumed_service = build_service(tmp_path, SearchThenFinishPolicy())
    completed, _ = resumed_service.resume(run.run_id)
    assert completed.status == AgentRunStatus.COMPLETED
    assert [step.decision.tool_name for step in completed.steps] == ["search_code", "finish"]


@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        (
            {
                "path": "../outside.txt",
                "line_start": 1,
                "line_end": 20,
                "focus_keyword": "secret",
                "reason": "try an escaping path",
            },
            "path escapes repository",
        ),
        (
            {
                "path": "agent.py",
                "line_start": 1,
                "line_end": 20,
                "focus_keyword": "ReActAgent",
                "unexpected": "must be rejected",
                "reason": "try an unknown argument",
            },
            "Extra inputs are not permitted",
        ),
    ],
)
def test_invalid_tool_arguments_are_visible_observations(
    sample_repo: Path,
    tmp_path: Path,
    arguments: dict[str, object],
    expected_error: str,
) -> None:
    service = build_service(tmp_path, InvalidReadPolicy(arguments))
    run = service.create(sample_repo, "Can the reader escape its boundary?", max_steps=1)
    completed, _ = service.execute(run)

    assert completed.status == AgentRunStatus.BUDGET_EXHAUSTED
    assert completed.steps[0].status == AgentStepStatus.TOOL_ERROR
    assert expected_error in completed.steps[0].observation.content
