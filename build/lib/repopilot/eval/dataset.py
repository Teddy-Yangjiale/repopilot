from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    """One localization task: a human-written issue, and the files its accepted fix changed.

    Ground truth comes from the merged pull request that closed the issue, so nobody labelled
    it by hand and nobody can argue with it. The issue text is the input a maintainer actually
    had — written before anyone knew which file was at fault.
    """

    case_id: str
    repo: str
    issue_number: int
    issue_url: str
    title: str
    body: str
    created_at: datetime

    pr_number: int
    # Kept so a later phase can check out the parent commit per case instead of evaluating
    # every case against one snapshot. See EvalRun.snapshot_sha for why that matters.
    base_sha: str
    gold_files: list[str] = Field(min_length=1)
    changed_files_total: int

    # A crash report often pastes the failing path. That is realistic input, not cheating, but
    # it inflates scores, so cases are flagged and reported separately rather than dropped.
    body_mentions_gold_path: bool

    def question(self, body_chars: int) -> str:
        """Issue bodies carry whole build logs; how much to feed the retriever is an eval axis."""

        if body_chars <= 0:
            return self.title
        return f"{self.title}\n\n{self.body[:body_chars]}".strip()


def load_dataset(path: Path) -> list[EvalCase]:
    with path.open(encoding="utf-8") as handle:
        return [EvalCase.model_validate_json(line) for line in handle if line.strip()]


def save_dataset(cases: list[EvalCase], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(case.model_dump_json() + "\n")
