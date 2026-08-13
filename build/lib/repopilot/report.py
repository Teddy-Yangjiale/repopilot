from __future__ import annotations

from pathlib import Path

from repopilot.models import TaskState
from repopilot.tools.git_tools import GitSnapshot


def render_markdown(state: TaskState, snapshot: GitSnapshot) -> str:
    evidence_by_id = {item.id: item for item in state.evidence}
    lines = [
        "# RepoPilot Investigation Report",
        "",
        f"- Task: `{state.task_id}`",
        f"- Stage: `{state.stage.value}`",
        f"- Repository: `{snapshot.root}`",
        f"- Git: `{snapshot.branch}` / `{snapshot.head[:12]}` / dirty=`{snapshot.dirty}`",
        f"- Question: {state.question}",
        f"- Keywords: {', '.join(state.keywords) or '(none)' }",
        f"- Query strategy: `{state.query_expansion.strategy.value}`",
        "",
        "## Verified findings",
        "",
    ]
    for item in state.verification:
        lines.append(f"- **{item.status.value}** — {item.statement}")
        lines.append(f"  - Gate: {item.reason}")
        for evidence_id in item.evidence_ids:
            evidence = evidence_by_id[evidence_id]
            lines.append(f"  - `{evidence.citation}` — {evidence.snippet}")

    lines.extend(["", "## Investigation plan", ""])
    for index, step in enumerate(state.plan, 1):
        lines.append(f"{index}. **{step.title}**")
        lines.append(f"   - Why: {step.rationale}")
        if step.verification_command:
            lines.append(f"   - Suggested read-only check: `{step.verification_command}`")

    lines.extend(
        [
            "",
            "## Evidence inventory",
            "",
            "| ID | Location | Keyword | Snippet |",
            "|---|---|---|---|",
        ]
    )
    for evidence in state.evidence:
        snippet = evidence.snippet.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{evidence.id}` | `{evidence.citation}` | `{evidence.keyword}` | {snippet} |"
        )
    lines.extend(
        [
            "",
            "## Scope and limitations",
            "",
            "This report proves text-level source matches only. It does not yet prove "
            "runtime execution, performance impact, issue intent, or test coverage. Those require "
            "call-graph analysis, GitHub evidence and controlled execution in later phases.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(state: TaskState, snapshot: GitSnapshot, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{state.task_id}.md"
    path.write_text(render_markdown(state, snapshot), encoding="utf-8")
    return path
