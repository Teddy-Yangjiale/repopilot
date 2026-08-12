from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from repopilot.container import get_orchestrator

app = typer.Typer(help="Evidence-driven repository maintenance agent.")


@app.command()
def investigate(
    repo: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    question: Annotated[str, typer.Option(min=3)],
    keyword: Annotated[list[str] | None, typer.Option("--keyword", "-k")] = None,
) -> None:
    """Create and run a repository investigation."""
    orchestrator = get_orchestrator()
    state = orchestrator.create_task(repo, question, keyword)
    final_state, report = orchestrator.run(state)
    typer.echo(f"task_id={final_state.task_id}")
    typer.echo(f"stage={final_state.stage.value}")
    typer.echo(f"evidence={len(final_state.evidence)}")
    typer.echo(f"report={report}")


@app.command()
def resume(task_id: str) -> None:
    """Resume an incomplete task from its last checkpoint."""
    state, report = get_orchestrator().resume(task_id)
    typer.echo(f"task_id={state.task_id}")
    typer.echo(f"stage={state.stage.value}")
    typer.echo(f"report={report}")


@app.command("tasks")
def list_tasks(limit: Annotated[int, typer.Option(min=1, max=100)] = 20) -> None:
    """List recent persisted tasks."""
    tasks = get_orchestrator().store.list(limit)
    if not tasks:
        typer.echo("No tasks yet.")
        return
    for state in tasks:
        typer.echo(
            f"{state.task_id}  {state.stage.value:14}  "
            f"{state.updated_at.isoformat()}  {state.question[:60]}"
        )


if __name__ == "__main__":
    app()
