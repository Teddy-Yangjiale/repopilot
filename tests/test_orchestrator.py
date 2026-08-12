from pathlib import Path

from repopilot.agents import InvestigatorAgent, PlannerAgent, VerifierAgent
from repopilot.models import TaskStage, VerificationStatus
from repopilot.orchestrator import RepoPilotOrchestrator
from repopilot.store import TaskStore
from repopilot.tools import CodeSearchTool, GitInspector


def build_orchestrator(tmp_path: Path) -> RepoPilotOrchestrator:
    return RepoPilotOrchestrator(
        investigator=InvestigatorAgent(CodeSearchTool()),
        planner=PlannerAgent(),
        verifier=VerifierAgent(),
        git_inspector=GitInspector(),
        store=TaskStore(tmp_path / "state" / "tasks.db"),
        report_dir=tmp_path / "state" / "reports",
    )


def test_end_to_end_task_is_persisted(sample_repo: Path, tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)
    state = orchestrator.create_task(
        sample_repo,
        "How does ReActAgent stop?",
        ["ReActAgent", "Finish"],
    )
    completed, report = orchestrator.run(state)

    assert completed.stage == TaskStage.COMPLETED
    assert completed.query_expansion.strategy.value == "explicit"
    assert completed.evidence
    assert all(item.status == VerificationStatus.VERIFIED for item in completed.verification)
    assert report.exists()
    assert orchestrator.store.load(completed.task_id).stage == TaskStage.COMPLETED


def test_resume_completed_task_is_idempotent(sample_repo: Path, tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)
    state = orchestrator.create_task(sample_repo, "Where is Finish?", ["Finish"])
    completed, first_report = orchestrator.run(state)
    resumed, second_report = orchestrator.resume(completed.task_id)
    assert resumed.model_dump() == completed.model_dump()
    assert first_report == second_report
