from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from repopilot.eval.agent_runner import (
    AgentEvalRun,
    aggregate_agent_results,
    render_agent_eval_markdown,
    run_agent_case,
    select_agent_eval_cases,
)
from repopilot.eval.dataset import EvalCase
from repopilot.runtime.models import AgentDecision, AgentRun
from repopilot.runtime.service import AgentService
from repopilot.runtime.store import AgentRunStore


class CompletePolicy:
    def decide(self, run: AgentRun, tool_schemas: list[dict]) -> AgentDecision:
        if not run.steps:
            return AgentDecision(
                tool_name="search_code",
                arguments={"keyword": "ReActAgent", "reason": "find the implementation"},
                reason="find the implementation",
            )
        return AgentDecision(
            tool_name="finish",
            arguments={
                "claims": [
                    {
                        "statement": "ReActAgent is present in the cited implementation file.",
                        "evidence_ids": [run.evidence[0].id],
                    }
                ],
                "limitations": ["Text evidence does not prove execution."],
                "reason": "the localization question is answered",
            },
            reason="the localization question is answered",
        )


class RepeatPolicy:
    def decide(self, run: AgentRun, tool_schemas: list[dict]) -> AgentDecision:
        return AgentDecision(
            tool_name="search_code",
            arguments={"keyword": "ReActAgent", "reason": "repeat the same search"},
            reason="repeat the same search",
        )


def make_case() -> EvalCase:
    return EvalCase(
        case_id="sample-1",
        repo="sample/repo",
        issue_number=1,
        issue_url="https://example.invalid/issues/1",
        title="Where is ReActAgent implemented?",
        body="Locate the implementation and explain it with evidence.",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        pr_number=2,
        base_sha="a" * 40,
        gold_files=["agent.py"],
        changed_files_total=1,
        body_mentions_gold_path=False,
    )


def make_service(tmp_path: Path, policy) -> AgentService:
    return AgentService(
        policy=policy,
        store=AgentRunStore(tmp_path / "agent-eval.db"),
        report_dir=tmp_path / "trajectories",
    )


def test_agent_eval_scores_completed_claim_level_citations(
    sample_repo: Path, tmp_path: Path
) -> None:
    result = run_agent_case(
        make_case(),
        sample_repo,
        make_service(tmp_path, CompletePolicy()),
        body_chars=600,
        max_steps=3,
        timeout_seconds=30,
    )
    metrics = aggregate_agent_results([result])

    assert result.status == "completed"
    assert result.evidence_files == ["agent.py"]
    assert result.final_citation_files == ["agent.py"]
    assert result.claim_citation_coverage == 1.0
    assert result.citation_integrity == 1.0
    assert metrics["completed_rate"] == 1.0
    assert metrics["final_hit_rate"] == 1.0
    assert metrics["clean_final_hit_rate"] == 1.0


def test_agent_eval_keeps_budget_failures_in_denominator(
    sample_repo: Path, tmp_path: Path
) -> None:
    result = run_agent_case(
        make_case(),
        sample_repo,
        make_service(tmp_path, RepeatPolicy()),
        body_chars=600,
        max_steps=2,
        timeout_seconds=30,
    )
    metrics = aggregate_agent_results([result])

    assert result.status == "budget_exhausted"
    assert result.tool_errors == 1
    assert metrics["completed_rate"] == 0.0
    assert metrics["budget_exhausted_rate"] == 1.0
    assert metrics["evidence_hit_rate"] == 1.0
    assert metrics["final_hit_rate"] == 0.0
    assert metrics["tool_error_step_rate"] == 0.5


def test_agent_eval_markdown_exposes_outcomes_and_failures(
    sample_repo: Path, tmp_path: Path
) -> None:
    result = run_agent_case(
        make_case(),
        sample_repo,
        make_service(tmp_path, RepeatPolicy()),
        body_chars=600,
        max_steps=2,
        timeout_seconds=30,
    )
    run = AgentEvalRun(
        dataset="cases.jsonl",
        repo_path=str(sample_repo),
        snapshot_sha="a" * 40,
        body_chars=600,
        max_steps=2,
        timeout_seconds=30,
        model="fake",
        metrics=aggregate_agent_results([result]),
        results=[result],
    )

    report = render_agent_eval_markdown(run)

    assert "Claim citation coverage" in report
    assert "Failure inventory" in report
    assert "search_code → search_code" in report


def test_clean_only_sampling_excludes_path_leaking_issues() -> None:
    leaking = make_case().model_copy(
        update={"case_id": "leaking", "body_mentions_gold_path": True}
    )
    clean_one = make_case().model_copy(update={"case_id": "clean-1"})
    clean_two = make_case().model_copy(update={"case_id": "clean-2"})

    selected = select_agent_eval_cases(
        [leaking, clean_one, clean_two], limit=1, clean_only=True
    )

    assert [case.case_id for case in selected] == ["clean-1"]
