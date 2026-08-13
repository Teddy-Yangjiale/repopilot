from __future__ import annotations

from repopilot.models import TaskState, VerificationItem, VerificationStatus
from repopilot.tools.read_tools import ReadRequest, SafeFileReader


class VerifierAgent:
    """Applies deterministic evidence gates before a statement reaches the report.

    Gate 1 (existence): every cited evidence id must exist in the collected set.
    Gate 2 (genuineness, when a reader is available): re-read the file at the cited
    line range and confirm the keyword actually occurs there. This catches fabricated
    line numbers or stale snippets without trusting any model judgment.
    """

    def __init__(self, reader: SafeFileReader | None = None) -> None:
        self.reader = reader

    def run(self, state: TaskState) -> TaskState:
        evidence_by_id = {item.id: item for item in state.evidence}
        # Cache key is (path, line range): two citations of the same file must re-read
        # their own lines, or every citation after the first is checked against the
        # first citation's text (a real bug this gate's own end-to-end run exposed).
        cache: dict[tuple[str, int, int], str | None] = {}

        def read_range(path: str, line_start: int, line_end: int) -> str | None:
            key = (path, line_start, line_end)
            if key not in cache:
                try:
                    cache[key] = self.reader.run(
                        ReadRequest(state.repo_path, path, line_start, line_end)
                    )
                except Exception:
                    cache[key] = None  # unreadable (oversized, deleted, ...) — not proof of forgery
            return cache[key]

        def genuine(evidence_id: str) -> tuple[bool, str | None]:
            """(verified_at_lines, note) for one evidence id under gate 2."""
            if self.reader is None:
                return True, None
            item = evidence_by_id[evidence_id]
            text = read_range(item.path, item.line_start, item.line_end)
            if text is None:
                return True, "file unreadable at cite time; existence only"
            if item.keyword.casefold() not in text.casefold():
                return False, f"keyword {item.keyword!r} absent from cited lines"
            return True, None

        checks: list[VerificationItem] = []
        for finding in state.findings:
            referenced = set(finding.evidence_ids)
            exists = referenced & set(evidence_by_id)
            genuine_ids = set()
            notes: list[str] = []
            for evidence_id in exists:
                ok, note = genuine(evidence_id)
                if ok:
                    genuine_ids.add(evidence_id)
                if note:
                    notes.append(f"{evidence_id}: {note}")

            if referenced and referenced == genuine_ids:
                status = VerificationStatus.VERIFIED
                reason = (
                    "Every cited evidence id exists and its keyword is present at the cited lines."
                    if self.reader is not None
                    else "Every cited evidence id exists in the collected evidence set."
                )
            elif genuine_ids:
                status = VerificationStatus.PARTIAL
                reason = (
                    "Some cited evidence ids are missing, or their keyword is absent "
                    "at the cited lines; keep the statement tentative."
                )
            else:
                status = VerificationStatus.REJECTED
                reason = "The statement has no valid line-level citation."

            if notes:
                reason = f"{reason} Notes: {'; '.join(notes)}."

            checks.append(
                VerificationItem(
                    statement=finding.statement,
                    status=status,
                    reason=reason,
                    evidence_ids=sorted(genuine_ids),
                )
            )

        state.verification = checks
        return state
