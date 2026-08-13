from __future__ import annotations

import json
from pathlib import Path

from repopilot.runtime.models import AgentRun


def render_agent_report(run: AgentRun) -> str:
    evidence_by_id = {item.id: item for item in run.evidence}
    lines = [
        "# RepoPilot Agent Run",
        "",
        f"- Run: `{run.run_id}`",
        f"- Status: `{run.status.value}`",
        f"- Repository: `{run.repo_path}`",
        f"- Question: {run.question}",
        f"- Steps: `{len(run.steps)}/{run.max_steps}`",
        f"- Tokens: `{run.total_tokens}`",
        "",
        "## Action / Observation trajectory",
        "",
    ]
    for step in run.steps:
        arguments = {
            key: value for key, value in step.decision.arguments.items() if key != "reason"
        }
        lines.extend(
            [
                f"### Step {step.index}: `{step.decision.tool_name}` — {step.status.value}",
                "",
                f"- Why: {step.decision.reason or '(not provided)'}",
                f"- Arguments: `{json.dumps(arguments, ensure_ascii=False)}`",
                f"- Latency: `{step.latency_ms} ms`",
                f"- Observation: {step.observation.content[:3000]}",
                "",
            ]
        )

    lines.extend(["## Final answer", "", run.final_answer or "_(no final answer)_", ""])
    if run.final_claims:
        lines.extend(["## Claim / evidence coverage", ""])
        for index, claim in enumerate(run.final_claims, start=1):
            citations = []
            for evidence_id in claim.evidence_ids:
                item = evidence_by_id.get(evidence_id)
                citations.append(item.citation if item else f"unknown:{evidence_id}")
            lines.append(f"{index}. {claim.statement} — {', '.join(citations)}")
        lines.append("")
    if run.final_evidence_ids:
        lines.extend(["## Final citations", ""])
        for evidence_id in run.final_evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item:
                lines.append(f"- `{evidence_id}` — `{item.citation}` — {item.snippet[:500]}")
        lines.append("")
    if run.error:
        lines.extend(["## Runtime status", "", run.error, ""])
    return "\n".join(lines)


def write_agent_report(run: AgentRun, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{run.run_id}.md"
    path.write_text(render_agent_report(run), encoding="utf-8")
    return path
