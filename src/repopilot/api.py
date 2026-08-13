from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from repopilot.container import get_orchestrator
from repopilot.models import TaskState

app = FastAPI(title="RepoPilot", version="0.11.0")


class InvestigateRequest(BaseModel):
    repo_path: Path
    question: str = Field(min_length=3)
    keywords: list[str] = Field(default_factory=list, max_length=10)
    use_llm: bool = False


class TaskResponse(BaseModel):
    task: TaskState
    report_path: Path


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/tasks/investigate", response_model=TaskResponse)
def investigate(request: InvestigateRequest) -> TaskResponse:
    orchestrator = get_orchestrator()
    try:
        state = orchestrator.create_task(
            request.repo_path,
            request.question,
            request.keywords,
            use_llm=request.use_llm,
        )
        state, report = orchestrator.run(state)
        return TaskResponse(task=state, report_path=report)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/tasks/{task_id}", response_model=TaskState)
def get_task(task_id: str) -> TaskState:
    try:
        return get_orchestrator().store.load(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v1/tasks/{task_id}/resume", response_model=TaskResponse)
def resume_task(task_id: str) -> TaskResponse:
    try:
        state, report = get_orchestrator().resume(task_id)
        return TaskResponse(task=state, report_path=report)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
