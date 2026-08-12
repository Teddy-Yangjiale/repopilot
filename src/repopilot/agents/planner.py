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

        evidence_by_path: dict[str, list[str]] = {}
        for evidence in state.evidence:
            evidence_by_path.setdefault(evidence.path, []).append(evidence.id)

        ranked_paths = sorted(
            evidence_by_path,
            key=lambda path: len(evidence_by_path[path]),
            reverse=True,
        )[:5]
        state.plan = [
            PlanStep(
                title=f"Inspect {path}",
                rationale=(
                    f"This file has {len(evidence_by_path[path])} matched location(s); "
                    "read surrounding definitions and callers before forming a causal claim."
                ),
                evidence_ids=evidence_by_path[path][:5],
                verification_command=f"rg -n --fixed-strings '<symbol>' {path}",
            )
            for path in ranked_paths
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
