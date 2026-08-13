from __future__ import annotations

from repopilot.models import PlanStep, TaskState


class PlannerAgent:
    """Turns collected evidence into an investigation plan without inventing code facts."""

    def run(self, state: TaskState) -> TaskState:
        if not state.evidence:
            state.plan = [
                PlanStep(
                    title="Refine retrieval query",
                    rationale="No source evidence was retrieved; conclusions would be unsupported.",
                )
            ]
            return state

        state.plan = [
            PlanStep(
                title=f"Inspect {file.path}",
                rationale=(
                    f"This file matches {file.keyword_count} query term(s) across "
                    f"{file.evidence_count} location(s); read surrounding definitions and "
                    "callers before forming a causal claim."
                ),
                evidence_ids=file.evidence_ids[:5],
                verification_command=f"git grep -n '<symbol>' -- {file.path}",
            )
            for file in state.ranked_files[:5]
        ]
        state.plan.append(
            PlanStep(
                title="Verify the end-to-end call path",
                rationale=(
                    "A matching identifier does not prove runtime execution; trace caller, guard, "
                    "tool result and termination condition before claiming behavior."
                ),
                evidence_ids=[item.id for item in state.evidence[:5]],
            )
        )
        return state
