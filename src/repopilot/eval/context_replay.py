from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from repopilot.eval.metrics import mean, percentile
from repopilot.runtime.context import ContextBuilder
from repopilot.runtime.models import AgentRun, AgentStepStatus


def replay_contexts(
    database: Path,
    decision_context_chars: int = 7_000,
    finalizer_context_chars: int = 9_000,
) -> dict[str, float]:
    """Replay persisted v0.18 runs without calling a model and compare prompt contexts."""

    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT state_json FROM agent_runs").fetchall()
    if not rows:
        raise ValueError(f"no Agent runs found in {database}")

    builder = ContextBuilder()
    old_decision: list[float] = []
    new_decision: list[float] = []
    old_finalizer: list[float] = []
    new_finalizer: list[float] = []
    dropped_steps = 0
    dropped_evidence = 0

    for row in rows:
        completed = AgentRun.model_validate_json(row[0])
        evidence = []
        for index, step in enumerate(completed.steps):
            prefix = completed.model_copy(
                update={
                    "steps": completed.steps[:index],
                    "evidence": evidence.copy(),
                    "decision_context_chars": decision_context_chars,
                    "finalizer_context_chars": finalizer_context_chars,
                }
            )
            if _should_finalize(prefix):
                old_finalizer.append(float(_size(_legacy_finalizer_context(prefix))))
                _, trace = builder.build_finalizer(prefix)
                new_finalizer.append(float(trace.chars_used))
            else:
                old_decision.append(float(_size(_legacy_decision_context(prefix))))
                _, trace = builder.build_decision(prefix)
                new_decision.append(float(trace.chars_used))
                dropped_steps += trace.steps_dropped
                dropped_evidence += trace.evidence_dropped
            known = {item.id for item in evidence}
            evidence.extend(item for item in step.observation.evidence if item.id not in known)

    return {
        "runs": float(len(rows)),
        "decision_calls": float(len(old_decision)),
        "legacy_decision_chars_mean": mean(old_decision),
        "new_decision_chars_mean": mean(new_decision),
        "decision_chars_change_rate": _change_rate(old_decision, new_decision),
        "legacy_decision_chars_p95": percentile(old_decision, 0.95),
        "new_decision_chars_p95": percentile(new_decision, 0.95),
        "new_decision_chars_max": max(new_decision, default=0.0),
        "finalizer_calls": float(len(old_finalizer)),
        "legacy_finalizer_chars_mean": mean(old_finalizer),
        "new_finalizer_chars_mean": mean(new_finalizer),
        "finalizer_chars_change_rate": _change_rate(old_finalizer, new_finalizer),
        "new_finalizer_chars_max": max(new_finalizer, default=0.0),
        "dropped_historical_steps": float(dropped_steps),
        "dropped_evidence_inventory_entries": float(dropped_evidence),
    }


def _should_finalize(run: AgentRun) -> bool:
    steps_remaining = run.max_steps - len(run.steps)
    successful_reads = sum(
        step.decision.tool_name == "read_file"
        and step.status == AgentStepStatus.SUCCEEDED
        for step in run.steps
    )
    tool_errors = sum(step.status == AgentStepStatus.TOOL_ERROR for step in run.steps)
    return bool(run.evidence) and (
        steps_remaining == 1
        or (successful_reads >= 2 and steps_remaining <= 2)
        or (successful_reads >= 1 and tool_errors >= 2)
    )


def _legacy_decision_context(run: AgentRun) -> dict[str, object]:
    history = [
        {
            "step": step.index,
            "tool": step.decision.tool_name,
            "arguments": {
                key: value
                for key, value in step.decision.arguments.items()
                if key != "reason"
            },
            "status": step.status.value,
            "observation": step.observation.content[:2_500],
            "evidence_ids": [item.id for item in step.observation.evidence],
        }
        for step in run.steps[-6:]
    ]
    return {
        "question": run.question,
        "step_budget_remaining": run.max_steps - len(run.steps),
        "collected_evidence_ids": [item.id for item in run.evidence],
        "recent_history": history,
    }


def _legacy_finalizer_context(run: AgentRun) -> dict[str, object]:
    read_evidence = [item for item in run.evidence if item.source == "agent_read_file"]
    other_evidence = [item for item in run.evidence if item.source != "agent_read_file"]
    selected = (read_evidence[-10:] + other_evidence[:10])[:20]
    return {
        "instruction": "Finalize the answer as JSON now.",
        "question": run.question,
        "evidence": [
            {
                "id": item.id,
                "citation": item.citation,
                "keyword": item.keyword,
                "snippet": item.snippet[:1_200],
            }
            for item in selected
        ],
    }


def _change_rate(old: list[float], new: list[float]) -> float:
    old_mean = mean(old)
    return mean(new) / old_mean - 1 if old_mean else 0.0


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
