from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from repopilot.container import get_orchestrator
from repopilot.query_expansion import LLMConfigurationError

app = typer.Typer(help="Evidence-driven repository maintenance agent.")


@app.command()
def investigate(
    repo: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    question: Annotated[str, typer.Option(min=3)],
    keyword: Annotated[list[str] | None, typer.Option("--keyword", "-k")] = None,
    use_llm: Annotated[
        bool,
        typer.Option("--use-llm/--no-llm", help="Use DeepSeek to expand search candidates."),
    ] = False,
) -> None:
    """Create and run a repository investigation."""
    orchestrator = get_orchestrator()
    state = orchestrator.create_task(repo, question, keyword, use_llm=use_llm)
    try:
        final_state, report = orchestrator.run(state)
    except LLMConfigurationError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"task_id={final_state.task_id}")
    typer.echo(f"stage={final_state.stage.value}")
    typer.echo(f"evidence={len(final_state.evidence)}")
    typer.echo(f"query_strategy={final_state.query_expansion.strategy.value}")
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
