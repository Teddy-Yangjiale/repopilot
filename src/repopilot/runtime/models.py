from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from repopilot.models import Evidence


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class AgentStepStatus(StrEnum):
    SUCCEEDED = "succeeded"
    TOOL_ERROR = "tool_error"


class AgentDecision(BaseModel):
    """One bounded action selected by a policy.

    `reason` is a concise audit summary, never hidden chain-of-thought.
    """

    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, object] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=500)
    model: str | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class ToolObservation(BaseModel):
    content: str = Field(max_length=20_000)
    evidence: list[Evidence] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class AgentStep(BaseModel):
    index: int = Field(ge=1)
    decision: AgentDecision
    status: AgentStepStatus
    observation: ToolObservation
    latency_ms: int = Field(ge=0)
    started_at: datetime = Field(default_factory=utc_now)


class CitedClaim(BaseModel):
    """One positive answer claim and the exact evidence IDs asserted to support it."""

    statement: str = Field(min_length=10, max_length=2_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class AgentRun(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    repo_path: Path
    question: str = Field(min_length=3)
    status: AgentRunStatus = AgentRunStatus.CREATED
    max_steps: int = Field(default=8, ge=1, le=30)
    timeout_seconds: float = Field(default=120.0, gt=0, le=1800)
    steps: list[AgentStep] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    final_answer: str | None = None
    final_claims: list[CitedClaim] = Field(default_factory=list)
    final_evidence_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def total_tokens(self) -> int:
        return sum(
            step.decision.prompt_tokens + step.decision.completion_tokens
            for step in self.steps
        )

    def touch(self) -> None:
        self.updated_at = utc_now()
