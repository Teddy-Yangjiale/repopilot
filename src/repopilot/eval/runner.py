from __future__ import annotations

import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from repopilot.agents import InvestigatorAgent
from repopilot.eval.dataset import EvalCase
from repopilot.eval.metrics import hit_at_k, mean, percentile, recall_at_k, reciprocal_rank
from repopilot.models import TaskState

DEFAULT_K_VALUES = (1, 5, 10)


@dataclass
class CaseResult:
    case_id: str
    gold_files: list[str]
    ranked_files: list[str]
    keywords: list[str]
    strategy: str
    evidence_count: int
    latency_ms: float
    body_mentions_gold_path: bool
    error: str | None = None


@dataclass
class EvalRun:
    """A score means nothing without the config that produced it, so both are one object."""

    dataset: str
    repo_path: str
    # Every case is scored against this one commit rather than its own parent commit. Cases whose
    # gold files no longer exist here were dropped at mining time; the fix being already present
    # is a known optimistic bias, recorded so it can be removed later using EvalCase.base_sha.
    snapshot_sha: str
    strategy: str
    body_chars: int
    max_results_per_keyword: int
    # Which ranking signals were switched on, so each ablation arm describes itself.
    ranking: str = "idf+prior"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metrics: dict[str, float] = field(default_factory=dict)
    results: list[CaseResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {**asdict(self), "results": [asdict(item) for item in self.results]}


def run_case(
    case: EvalCase,
    repo_path: Path,
    investigator: InvestigatorAgent,
    body_chars: int,
    use_llm: bool,
) -> CaseResult:
    state = TaskState(
        repo_path=repo_path,
        question=case.question(body_chars),
        use_llm=use_llm,
    )
    started = time.perf_counter()
    try:
        state = investigator.run(state)
    except Exception as exc:  # one unanswerable case must not abort a 50-case run
        return CaseResult(
            case_id=case.case_id,
            gold_files=case.gold_files,
            ranked_files=[],
            keywords=state.keywords,
            strategy=state.query_expansion.strategy.value,
            evidence_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            body_mentions_gold_path=case.body_mentions_gold_path,
            error=f"{type(exc).__name__}: {exc}"[:300],
        )

    return CaseResult(
        case_id=case.case_id,
        gold_files=case.gold_files,
        # Truncated: metrics never look past k=10, and 60 full rankings would bloat the report.
        ranked_files=[file.path for file in state.ranked_files[:20]],
        keywords=state.keywords,
        strategy=state.query_expansion.strategy.value,
        evidence_count=len(state.evidence),
        latency_ms=(time.perf_counter() - started) * 1000,
        body_mentions_gold_path=case.body_mentions_gold_path,
    )


def aggregate(
    results: list[CaseResult], k_values: tuple[int, ...] = DEFAULT_K_VALUES
) -> dict[str, float]:
    scored = [item for item in results if item.error is None]
    metrics: dict[str, float] = {
        "cases": float(len(results)),
        "errors": float(len(results) - len(scored)),
        "zero_evidence_rate": mean([float(item.evidence_count == 0) for item in scored]),
        "mrr": mean([reciprocal_rank(item.gold_files, item.ranked_files) for item in scored]),
        "latency_p50_ms": percentile([item.latency_ms for item in results], 0.50),
        "latency_p95_ms": percentile([item.latency_ms for item in results], 0.95),
    }
    for k in k_values:
        metrics[f"recall@{k}"] = mean(
            [recall_at_k(item.gold_files, item.ranked_files, k) for item in scored]
        )
        metrics[f"hit@{k}"] = mean(
            [hit_at_k(item.gold_files, item.ranked_files, k) for item in scored]
        )

    # The same numbers on cases whose text never names a gold file: the honest lower bound.
    clean = [item for item in scored if not item.body_mentions_gold_path]
    metrics["clean_cases"] = float(len(clean))
    for k in k_values:
        metrics[f"clean_recall@{k}"] = mean(
            [recall_at_k(item.gold_files, item.ranked_files, k) for item in clean]
        )
        metrics[f"clean_hit@{k}"] = mean(
            [hit_at_k(item.gold_files, item.ranked_files, k) for item in clean]
        )
    return metrics


def resolve_snapshot_sha(repo_path: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    return completed.stdout.strip()


def render_markdown(run: EvalRun, k_values: tuple[int, ...] = DEFAULT_K_VALUES) -> str:
    metrics = run.metrics
    lines = [
        "# RepoPilot Retrieval Baseline",
        "",
        f"- Dataset: `{run.dataset}`",
        f"- Repository: `{run.repo_path}` @ `{run.snapshot_sha[:12]}`",
        f"- Strategy: `{run.strategy}`  |  ranking: `{run.ranking}`",
        f"- Question body budget: `{run.body_chars}` chars",
        f"- Max search results per keyword: `{run.max_results_per_keyword}`",
        f"- Run at: {run.created_at}",
        "",
        "## Metrics",
        "",
        "| Metric | All cases | Cases not naming a gold file |",
        "|---|---:|---:|",
    ]
    for k in k_values:
        lines.append(
            f"| Recall@{k} | {metrics.get(f'recall@{k}', 0):.3f} "
            f"| {metrics.get(f'clean_recall@{k}', 0):.3f} |"
        )
    for k in k_values:
        lines.append(
            f"| Hit@{k} | {metrics.get(f'hit@{k}', 0):.3f} "
            f"| {metrics.get(f'clean_hit@{k}', 0):.3f} |"
        )
    lines.extend(
        [
            f"| MRR | {metrics.get('mrr', 0):.3f} | — |",
            f"| Zero-evidence rate | {metrics.get('zero_evidence_rate', 0):.3f} | — |",
            f"| Cases | {int(metrics.get('cases', 0))} | {int(metrics.get('clean_cases', 0))} |",
            f"| Errors | {int(metrics.get('errors', 0))} | — |",
            f"| Latency p50 / p95 | {metrics.get('latency_p50_ms', 0):.0f} ms "
            f"/ {metrics.get('latency_p95_ms', 0):.0f} ms | — |",
            "",
            "## Worst cases",
            "",
            "| Case | Gold files | Top-3 predicted | Keywords |",
            "|---|---|---|---|",
        ]
    )
    worst = sorted(
        run.results, key=lambda item: reciprocal_rank(item.gold_files, item.ranked_files)
    )
    for item in worst[:10]:
        gold = ", ".join(f"`{path}`" for path in item.gold_files[:2])
        predicted = ", ".join(f"`{path}`" for path in item.ranked_files[:3]) or "_(none)_"
        keywords = ", ".join(f"`{word}`" for word in item.keywords[:5]) or "_(none)_"
        lines.append(f"| {item.case_id} | {gold} | {predicted} | {keywords} |")
    lines.append("")
    return "\n".join(lines)
