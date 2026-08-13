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


class QueryExpansionStrategy(StrEnum):
    EXPLICIT = "explicit"
    DETERMINISTIC = "deterministic"
    HYBRID = "hybrid"
    HYBRID_FALLBACK = "hybrid_fallback"


class QueryExpansionTrace(BaseModel):
    """Auditable record of how repository search terms were selected."""

    strategy: QueryExpansionStrategy = QueryExpansionStrategy.DETERMINISTIC
    baseline_keywords: list[str] = Field(default_factory=list)
    llm_keywords: list[str] = Field(default_factory=list)
    model: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    warning: str | None = None


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


class RankedFile(BaseModel):
    """A scored candidate location. Persisted because the ranking *is* the retrieval answer."""

    path: str
    score: float
    keyword_count: int
    evidence_count: int
    evidence_ids: list[str] = Field(default_factory=list)


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
    use_llm: bool = False
    query_expansion: QueryExpansionTrace = Field(default_factory=QueryExpansionTrace)
    stage: TaskStage = TaskStage.CREATED
    evidence: list[Evidence] = Field(default_factory=list)
    ranked_files: list[RankedFile] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    plan: list[PlanStep] = Field(default_factory=list)
    verification: list[VerificationItem] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def checkpoint(self, stage: TaskStage) -> None:
        self.stage = stage
        self.updated_at = utc_now()
