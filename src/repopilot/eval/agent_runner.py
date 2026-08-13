from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from repopilot.eval.dataset import EvalCase
from repopilot.eval.metrics import hit_at_k, mean, percentile, recall_at_k
from repopilot.eval.runner import (
    _add_base_worktree,
    _remove_base_worktree,
    resolve_snapshot_sha,
)
from repopilot.runtime.models import AgentRunStatus, AgentStepStatus
from repopilot.runtime.service import AgentService


@dataclass
class AgentCaseResult:
    case_id: str
    issue_url: str
    gold_files: list[str]
    evidence_files: list[str]
    final_citation_files: list[str]
    status: str
    steps: int
    tokens: int
    latency_ms: float
    tool_calls: list[str]
    tool_errors: int
    relocated_reads: int
    evidence_count: int
    final_claims: int
    claim_citation_coverage: float
    citation_integrity: float
    body_mentions_gold_path: bool
    report_path: str | None = None
    gold_missing_at_base: bool = False
    base_unavailable: bool = False
    error: str | None = None


@dataclass
class AgentEvalRun:
    dataset: str
    repo_path: str
    snapshot_sha: str
    body_chars: int
    max_steps: int
    timeout_seconds: float
    model: str
    at_base: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metrics: dict[str, float] = field(default_factory=dict)
    results: list[AgentCaseResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {**asdict(self), "results": [asdict(item) for item in self.results]}


def _ordered_unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def select_agent_eval_cases(
    cases: list[EvalCase], limit: int, clean_only: bool = False
) -> list[EvalCase]:
    """Deterministic paid-eval sampling, optionally excluding path-leaking issue text."""

    eligible = (
        [case for case in cases if not case.body_mentions_gold_path]
        if clean_only
        else cases
    )
    return eligible[:limit]


def run_agent_case(
    case: EvalCase,
    repo_path: Path,
    service: AgentService,
    body_chars: int,
    max_steps: int,
    timeout_seconds: float,
    at_base: bool = False,
) -> AgentCaseResult:
    """Run one real issue through the dynamic Agent and retain its complete trajectory."""

    worktree: Path | None = None
    target = repo_path
    gold_missing = False
    base_unavailable = False
    if at_base and case.base_sha:
        try:
            worktree = _add_base_worktree(repo_path, case.base_sha)
        except Exception:
            base_unavailable = True
        else:
            target = worktree
            gold_missing = any(not (target / gold).exists() for gold in case.gold_files)

    if base_unavailable:
        return AgentCaseResult(
            case_id=case.case_id,
            issue_url=case.issue_url,
            gold_files=case.gold_files,
            evidence_files=[],
            final_citation_files=[],
            status=AgentRunStatus.FAILED,
            steps=0,
            tokens=0,
            latency_ms=0.0,
            tool_calls=[],
            tool_errors=0,
            relocated_reads=0,
            evidence_count=0,
            final_claims=0,
            claim_citation_coverage=0.0,
            citation_integrity=0.0,
            body_mentions_gold_path=case.body_mentions_gold_path,
            base_unavailable=True,
            error="base commit unavailable; case was not evaluated against repository HEAD",
        )

    run = service.create(
        target,
        case.question(body_chars),
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
    )
    report: Path | None = None
    started = time.perf_counter()
    exception_error: str | None = None
    try:
        run, report = service.execute(run)
    except Exception as exc:  # one provider failure must not abort the benchmark
        exception_error = f"{type(exc).__name__}: {exc}"[:500]
        run = service.store.load(run.run_id)
    finally:
        latency_ms = (time.perf_counter() - started) * 1000
        if worktree is not None:
            _remove_base_worktree(repo_path, worktree)

    evidence_files = _ordered_unique([item.path for item in run.evidence])
    evidence_by_id = {item.id: item for item in run.evidence}
    final_citation_files = _ordered_unique(
        [
            evidence_by_id[evidence_id].path
            for evidence_id in run.final_evidence_ids
            if evidence_id in evidence_by_id
        ]
    )
    covered_claims = sum(
        1
        for claim in run.final_claims
        if claim.evidence_ids
        and all(evidence_id in evidence_by_id for evidence_id in claim.evidence_ids)
    )
    claim_coverage = covered_claims / len(run.final_claims) if run.final_claims else 0.0
    citation_integrity = float(
        bool(run.final_evidence_ids)
        and all(evidence_id in evidence_by_id for evidence_id in run.final_evidence_ids)
    )
    return AgentCaseResult(
        case_id=case.case_id,
        issue_url=case.issue_url,
        gold_files=case.gold_files,
        evidence_files=evidence_files,
        final_citation_files=final_citation_files,
        status=run.status.value,
        steps=len(run.steps),
        tokens=run.total_tokens,
        latency_ms=latency_ms,
        tool_calls=[step.decision.tool_name for step in run.steps],
        tool_errors=sum(step.status == AgentStepStatus.TOOL_ERROR for step in run.steps),
        relocated_reads=sum(
            step.decision.tool_name == "read_file"
            and step.observation.metadata.get("relocated") is True
            for step in run.steps
        ),
        evidence_count=len(run.evidence),
        final_claims=len(run.final_claims),
        claim_citation_coverage=claim_coverage,
        citation_integrity=citation_integrity,
        body_mentions_gold_path=case.body_mentions_gold_path,
        report_path=str(report) if report else None,
        gold_missing_at_base=gold_missing,
        base_unavailable=base_unavailable,
        error=exception_error or run.error,
    )


def aggregate_agent_results(results: list[AgentCaseResult]) -> dict[str, float]:
    completed = [item for item in results if item.status == AgentRunStatus.COMPLETED]
    clean = [item for item in results if not item.body_mentions_gold_path]
    total_steps = sum(item.steps for item in results)
    tool_names = sorted({tool for item in results for tool in item.tool_calls})
    metrics: dict[str, float] = {
        "cases": float(len(results)),
        "completed_rate": mean(
            [float(item.status == AgentRunStatus.COMPLETED) for item in results]
        ),
        "budget_exhausted_rate": mean(
            [float(item.status == AgentRunStatus.BUDGET_EXHAUSTED) for item in results]
        ),
        "failed_rate": mean(
            [float(item.status == AgentRunStatus.FAILED) for item in results]
        ),
        "evidence_hit_rate": mean(
            [
                hit_at_k(item.gold_files, item.evidence_files, len(item.evidence_files))
                for item in results
            ]
        ),
        "evidence_recall": mean(
            [
                recall_at_k(item.gold_files, item.evidence_files, len(item.evidence_files))
                for item in results
            ]
        ),
        "final_hit_rate": mean(
            [
                hit_at_k(
                    item.gold_files,
                    item.final_citation_files,
                    len(item.final_citation_files),
                )
                for item in results
            ]
        ),
        "final_recall": mean(
            [
                recall_at_k(
                    item.gold_files,
                    item.final_citation_files,
                    len(item.final_citation_files),
                )
                for item in results
            ]
        ),
        "clean_cases": float(len(clean)),
        "clean_final_hit_rate": mean(
            [
                hit_at_k(
                    item.gold_files,
                    item.final_citation_files,
                    len(item.final_citation_files),
                )
                for item in clean
            ]
        ),
        "claim_citation_coverage": mean(
            [item.claim_citation_coverage for item in completed]
        ),
        "citation_integrity_rate": mean([item.citation_integrity for item in completed]),
        "zero_evidence_rate": mean([float(item.evidence_count == 0) for item in results]),
        "tool_error_step_rate": (
            sum(item.tool_errors for item in results) / total_steps if total_steps else 0.0
        ),
        "relocated_reads": float(sum(item.relocated_reads for item in results)),
        "steps_mean": mean([float(item.steps) for item in results]),
        "steps_p50": percentile([float(item.steps) for item in results], 0.50),
        "steps_p95": percentile([float(item.steps) for item in results], 0.95),
        "tokens_mean": mean([float(item.tokens) for item in results]),
        "tokens_p50": percentile([float(item.tokens) for item in results], 0.50),
        "tokens_p95": percentile([float(item.tokens) for item in results], 0.95),
        "latency_p50_ms": percentile([item.latency_ms for item in results], 0.50),
        "latency_p95_ms": percentile([item.latency_ms for item in results], 0.95),
        "base_unavailable": float(sum(item.base_unavailable for item in results)),
        "gold_missing_at_base": float(sum(item.gold_missing_at_base for item in results)),
    }
    for tool_name in tool_names:
        metrics[f"tool_calls_{tool_name}"] = float(
            sum(item.tool_calls.count(tool_name) for item in results)
        )
    return metrics


def build_agent_eval_run(
    dataset: Path,
    repo_path: Path,
    body_chars: int,
    max_steps: int,
    timeout_seconds: float,
    model: str,
    at_base: bool,
    results: list[AgentCaseResult],
) -> AgentEvalRun:
    return AgentEvalRun(
        dataset=str(dataset),
        repo_path=str(repo_path),
        snapshot_sha=resolve_snapshot_sha(repo_path),
        body_chars=body_chars,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
        model=model,
        at_base=at_base,
        metrics=aggregate_agent_results(results),
        results=results,
    )


def render_agent_eval_markdown(run: AgentEvalRun) -> str:
    metrics = run.metrics
    lines = [
        "# RepoPilot Agent Evaluation",
        "",
        f"- Dataset: `{run.dataset}`",
        f"- Repository: `{run.repo_path}` @ `{run.snapshot_sha[:12]}`",
        f"- Model: `{run.model}`",
        f"- Budget: `{run.max_steps}` steps / `{run.timeout_seconds:.0f}` seconds per case",
        f"- Evaluated at: `{'PR base commit' if run.at_base else 'repository HEAD'}`",
        f"- Run at: {run.created_at}",
        "",
        "## Outcome metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Cases | {int(metrics.get('cases', 0))} |",
        f"| Completed | {metrics.get('completed_rate', 0):.3f} |",
        f"| Budget exhausted | {metrics.get('budget_exhausted_rate', 0):.3f} |",
        f"| Gold file found in any evidence | {metrics.get('evidence_hit_rate', 0):.3f} |",
        f"| Gold file present in final citations | {metrics.get('final_hit_rate', 0):.3f} |",
        f"| Clean final hit rate | {metrics.get('clean_final_hit_rate', 0):.3f} |",
        f"| Claim citation coverage | {metrics.get('claim_citation_coverage', 0):.3f} |",
        f"| Citation integrity | {metrics.get('citation_integrity_rate', 0):.3f} |",
        f"| Tool-error step rate | {metrics.get('tool_error_step_rate', 0):.3f} |",
        f"| Stale read ranges relocated | {int(metrics.get('relocated_reads', 0))} |",
        (
            f"| Mean steps / tokens | {metrics.get('steps_mean', 0):.2f} / "
            f"{metrics.get('tokens_mean', 0):.0f} |"
        ),
        (
            f"| Latency p50 / p95 | {metrics.get('latency_p50_ms', 0):.0f} / "
            f"{metrics.get('latency_p95_ms', 0):.0f} ms |"
        ),
        "",
        "## Per-case results",
        "",
        "| Case | Status | Gold hit (evidence/final) | Steps | Tokens | Tool errors |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in run.results:
        evidence_hit = int(bool(set(item.gold_files) & set(item.evidence_files)))
        final_hit = int(bool(set(item.gold_files) & set(item.final_citation_files)))
        lines.append(
            f"| [{item.case_id}]({item.issue_url}) | {item.status} | "
            f"{evidence_hit}/{final_hit} | {item.steps} | {item.tokens} | {item.tool_errors} |"
        )

    failures = [item for item in run.results if item.status != AgentRunStatus.COMPLETED]
    if failures:
        lines.extend(["", "## Failure inventory", ""])
        for item in failures:
            calls = " → ".join(item.tool_calls) or "_(no actions)_"
            lines.append(f"- `{item.case_id}` — {item.error or item.status}; tools: {calls}")
    lines.append("")
    return "\n".join(lines)
