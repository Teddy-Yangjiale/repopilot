from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskStage(StrEnum):
    CREATED = "created"
    INVESTIGATING = "investigating"
    PLANNING = "planning"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    REJECTED = "rejected"


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: f"ev-{uuid4().hex[:10]}")
    path: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    snippet: str
    keyword: str
    source: str = "local_code_search"

    @model_validator(mode="after")
    def validate_lines(self) -> Evidence:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self

    @property
    def citation(self) -> str:
        return f"{self.path}:{self.line_start}-{self.line_end}"


class Finding(BaseModel):
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PlanStep(BaseModel):
    title: str
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    verification_command: str | None = None


class VerificationItem(BaseModel):
    statement: str
    status: VerificationStatus
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class TaskState(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid4().hex)
    repo_path: Path
    question: str = Field(min_length=3)
    keywords: list[str] = Field(default_factory=list)
    stage: TaskStage = TaskStage.CREATED
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    plan: list[PlanStep] = Field(default_factory=list)
    verification: list[VerificationItem] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def checkpoint(self, stage: TaskStage) -> None:
        self.stage = stage
        self.updated_at = utc_now()
