from __future__ import annotations

from repopilot.models import TaskState, VerificationItem, VerificationStatus


class VerifierAgent:
    """Applies deterministic evidence gates before a statement reaches the report."""

    def run(self, state: TaskState) -> TaskState:
        evidence_ids = {item.id for item in state.evidence}
        checks: list[VerificationItem] = []

        for finding in state.findings:
            referenced = set(finding.evidence_ids)
            valid = referenced & evidence_ids
            if referenced and referenced == valid:
                status = VerificationStatus.VERIFIED
                reason = "Every cited evidence id exists in the collected evidence set."
            elif valid:
                status = VerificationStatus.PARTIAL
                reason = "Some cited evidence ids are missing; keep the statement tentative."
            else:
                status = VerificationStatus.REJECTED
                reason = "The statement has no valid line-level citation."
            checks.append(
                VerificationItem(
                    statement=finding.statement,
                    status=status,
                    reason=reason,
                    evidence_ids=sorted(valid),
                )
            )

        state.verification = checks
        return state
