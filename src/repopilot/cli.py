from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from repopilot import __version__
from repopilot.container import get_orchestrator
from repopilot.query_expansion import LLMConfigurationError
from repopilot.ranking import DEFAULT_VENDORED_PENALTY

app = typer.Typer(help="Evidence-driven repository maintenance agent.")

# Load .env at the CLI level so every command (not just the orchestrator-built ones)
# can read LLM_* settings; load_dotenv is idempotent and override=False.
load_dotenv(Path.cwd() / ".env", override=False)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True),
    ] = None,
) -> None:
    """RepoPilot command line interface."""


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


def _agent_service():
    from repopilot.config import Settings
    from repopilot.runtime.policy import DeepSeekToolPolicy
    from repopilot.runtime.service import AgentService
    from repopilot.runtime.store import AgentRunStore

    state_dir = Settings().resolve_state_dir()
    return AgentService(
        policy=DeepSeekToolPolicy(),
        store=AgentRunStore(state_dir / "agent_runs.db"),
        report_dir=state_dir / "agent_reports",
    )


@app.command("agent")
def run_agent(
    repo: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    question: Annotated[str, typer.Option(min=3)],
    max_steps: Annotated[int, typer.Option(min=1, max=30)] = 8,
    timeout_seconds: Annotated[float, typer.Option(min=1, max=1800)] = 120,
    context_chars: Annotated[int, typer.Option(min=2_000, max=100_000)] = 7_000,
    finalizer_context_chars: Annotated[
        int, typer.Option(min=2_000, max=100_000)
    ] = 9_000,
) -> None:
    """Run the bounded DeepSeek Plan-Act-Observe investigation loop."""
    service = _agent_service()
    run = service.create(
        repo,
        question,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
        decision_context_chars=context_chars,
        finalizer_context_chars=finalizer_context_chars,
    )
    try:
        run, report = service.execute(run)
    except LLMConfigurationError as exc:
        typer.echo(f"run_id={run.run_id}")
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"run_id={run.run_id}")
    typer.echo(f"status={run.status.value}")
    typer.echo(f"steps={len(run.steps)}")
    typer.echo(f"evidence={len(run.evidence)}")
    typer.echo(f"tokens={run.total_tokens}")
    typer.echo(f"report={report}")


@app.command("agent-resume")
def resume_agent(run_id: str) -> None:
    """Resume an Agent run from its persisted Action/Observation trajectory."""
    try:
        run, report = _agent_service().resume(run_id)
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"run_id={run.run_id}")
    typer.echo(f"status={run.status.value}")
    typer.echo(f"steps={len(run.steps)}")
    typer.echo(f"report={report}")


@app.command("agent-eval")
def run_agent_eval(
    dataset: Annotated[Path, typer.Option(exists=True, dir_okay=False, resolve_path=True)],
    repo: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    out: Annotated[Path, typer.Option(resolve_path=True)] = Path(".repopilot/agent-eval"),
    body_chars: Annotated[int, typer.Option(min=0, max=20_000)] = 1_200,
    limit: Annotated[
        int,
        typer.Option(min=1, max=100, help="Paid model cases to run; default is deliberately 5."),
    ] = 5,
    clean_only: Annotated[
        bool,
        typer.Option(
            "--clean-only/--all-cases",
            help="Exclude issues whose text already names a merged-PR gold file.",
        ),
    ] = False,
    max_steps: Annotated[int, typer.Option(min=1, max=30)] = 8,
    timeout_seconds: Annotated[float, typer.Option(min=1, max=1800)] = 120,
    context_chars: Annotated[int, typer.Option(min=2_000, max=100_000)] = 7_000,
    finalizer_context_chars: Annotated[
        int, typer.Option(min=2_000, max=100_000)
    ] = 9_000,
    at_base: Annotated[
        bool,
        typer.Option(
            "--at-base/--at-head",
            help="Run each issue on its pre-merge PR base commit via a temporary worktree.",
        ),
    ] = False,
) -> None:
    """Evaluate multi-step Agent trajectories against merged-PR gold files."""
    from repopilot.eval.agent_runner import (
        build_agent_eval_run,
        render_agent_eval_markdown,
        run_agent_case,
        select_agent_eval_cases,
    )
    from repopilot.eval.dataset import load_dataset
    from repopilot.llm.deepseek import DeepSeekConfig
    from repopilot.runtime.policy import DeepSeekToolPolicy
    from repopilot.runtime.service import AgentService
    from repopilot.runtime.store import AgentRunStore

    try:
        config = DeepSeekConfig.from_env()
    except LLMConfigurationError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    cases = select_agent_eval_cases(load_dataset(dataset), limit, clean_only=clean_only)
    out.mkdir(parents=True, exist_ok=True)
    service = AgentService(
        policy=DeepSeekToolPolicy(config),
        store=AgentRunStore(out / "agent_eval.db"),
        report_dir=out / "trajectories",
    )
    results = []
    with typer.progressbar(cases, label="Evaluating Agent") as progress:
        for case in progress:
            results.append(
                run_agent_case(
                    case,
                    repo,
                    service,
                    body_chars=body_chars,
                    max_steps=max_steps,
                    timeout_seconds=timeout_seconds,
                    at_base=at_base,
                    decision_context_chars=context_chars,
                    finalizer_context_chars=finalizer_context_chars,
                )
            )

    run = build_agent_eval_run(
        dataset,
        repo,
        body_chars,
        max_steps,
        timeout_seconds,
        context_chars,
        finalizer_context_chars,
        config.model,
        at_base,
        results,
    )
    dataset_tag = dataset.stem.replace("-issues", "")
    snapshot_tag = "base" if at_base else "head"
    stem = f"{dataset_tag}-agent-{snapshot_tag}-n{len(cases)}"
    json_path = out / f"{stem}.json"
    report_path = out / f"{stem}.md"
    json_path.write_text(json.dumps(run.as_dict(), indent=2), encoding="utf-8")
    report_path.write_text(render_agent_eval_markdown(run), encoding="utf-8")
    for key, value in run.metrics.items():
        typer.echo(f"{key}={value:.3f}")
    typer.echo(f"report={report_path}")


@app.command("context-replay")
def replay_agent_context(
    database: Annotated[Path, typer.Option(exists=True, dir_okay=False, resolve_path=True)],
    context_chars: Annotated[int, typer.Option(min=2_000, max=100_000)] = 7_000,
    finalizer_context_chars: Annotated[
        int, typer.Option(min=2_000, max=100_000)
    ] = 9_000,
) -> None:
    """Compare v0.18 and current contexts from a saved Agent evaluation database."""
    from repopilot.eval.context_replay import replay_contexts

    metrics = replay_contexts(database, context_chars, finalizer_context_chars)
    typer.echo(json.dumps(metrics, indent=2))


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


@app.command("dataset-build")
def dataset_build(
    clone: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    out: Annotated[Path, typer.Option()],
    repo: Annotated[str, typer.Option(help="GitHub slug, e.g. opencv/opencv")] = "opencv/opencv",
    limit: Annotated[int, typer.Option(min=1, max=500)] = 50,
    max_changed_files: Annotated[int, typer.Option(min=1, max=100)] = 10,
    backend: Annotated[
        str,
        typer.Option(help="graphql (issue -> merged PR) or rest (merged PR -> closes ref)"),
    ] = "graphql",
) -> None:
    """Build a localization dataset from closed issues fixed by a merged pull request."""
    from repopilot.eval.dataset import save_dataset
    from repopilot.eval.mining import DatasetMiningError, mine_dataset
    from repopilot.eval.mining_rest import mine_dataset_rest
    from repopilot.tools.search_tools import list_tracked_files

    tracked = set(list_tracked_files(clone))
    try:
        if backend == "rest":
            result = mine_dataset_rest(
                repo, tracked, limit=limit, max_changed_files=max_changed_files
            )
        else:
            result = mine_dataset(repo, tracked, limit=limit, max_changed_files=max_changed_files)
    except DatasetMiningError as exc:
        typer.echo(f"Dataset error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    save_dataset(result.cases, out)
    typer.echo(f"dataset={out}")
    typer.echo(f"cases={len(result.cases)}")
    for reason, count in result.stats.as_dict().items():
        typer.echo(f"  {reason}={count}")


@app.command("eval")
def run_eval(
    dataset: Annotated[Path, typer.Option(exists=True, dir_okay=False, resolve_path=True)],
    repo: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    out: Annotated[Path, typer.Option(resolve_path=True)] = Path(".repopilot/eval"),
    body_chars: Annotated[int, typer.Option(min=0, max=20_000)] = 600,
    limit: Annotated[int, typer.Option(min=0, help="0 runs the whole dataset")] = 0,
    use_llm: Annotated[bool, typer.Option("--use-llm/--no-llm")] = False,
    use_idf: Annotated[
        bool, typer.Option("--idf/--no-idf", help="Weight rare terms higher.")
    ] = True,
    vendored_penalty: Annotated[
        float,
        typer.Option(min=0.0, max=1.0, help="Score multiplier for vendored dirs; 1.0 disables."),
    ] = DEFAULT_VENDORED_PENALTY,
    length_norm: Annotated[
        bool,
        typer.Option("--length-norm/--no-length-norm",
                     help="Dilute term frequency by doc length (experimental)."),
    ] = False,
    at_base: Annotated[
        bool,
        typer.Option(
            "--at-base/--at-head",
            help="Evaluate each case on its PR base commit (pre-merge code) via worktree.",
        ),
    ] = False,
    refine_symbols: Annotated[
        bool,
        typer.Option(
            "--refine-symbols/--no-refine-symbols",
            help="Feed hit lines' enclosing function names back into the search to recall callers.",
        ),
    ] = False,
    definition_bonus: Annotated[
        float,
        typer.Option(
            min=0.0, max=5.0,
            help="Extra weight per definition hit (hit on a function signature); 0 disables.",
        ),
    ] = 0.0,
) -> None:
    """Score retrieval against a dataset and write a reproducible report."""
    from repopilot.agents import InvestigatorAgent
    from repopilot.config import Settings
    from repopilot.eval.dataset import load_dataset
    from repopilot.eval.runner import (
        EvalRun,
        aggregate,
        render_markdown,
        resolve_snapshot_sha,
        run_case,
    )
    from repopilot.llm import DeepSeekKeywordGenerator
    from repopilot.query_expansion import HybridQueryExpander
    from repopilot.tools import CodeSearchTool

    settings = Settings()
    cases = load_dataset(dataset)
    if limit:
        cases = cases[:limit]

    if use_llm:
        # Fail fast on configuration before running a single case: otherwise every case
        # would report the same LLMConfigurationError and waste a full eval run.
        from repopilot.llm.deepseek import DeepSeekConfig
        from repopilot.query_expansion import LLMConfigurationError

        try:
            DeepSeekConfig.from_env()
        except LLMConfigurationError as exc:
            typer.echo(f"Configuration error: {exc}", err=True)
            raise typer.Exit(code=2) from exc

    investigator = InvestigatorAgent(
        search_tool=CodeSearchTool(),
        query_expander=HybridQueryExpander(generator=DeepSeekKeywordGenerator()),
        max_results_per_keyword=settings.max_search_results,
        context_lines=settings.context_lines,
        timeout_seconds=settings.search_timeout_seconds,
        use_idf=use_idf,
        vendored_penalty=vendored_penalty,
        use_length_norm=length_norm,
        refine_symbols=refine_symbols,
        definition_bonus=definition_bonus,
    )

    results = []
    with typer.progressbar(cases, label="Evaluating") as progress:
        for case in progress:
            results.append(
                run_case(case, repo, investigator, body_chars, use_llm, at_base=at_base)
            )

    ranking = "+".join(
        part
        for part in (
            "idf" if use_idf else "",
            "prior" if vendored_penalty < 1.0 else "",
            "len" if length_norm else "",
            "sym" if refine_symbols else "",
            "def" if definition_bonus > 0 else "",
        )
        if part
    ) or "none"
    run = EvalRun(
        dataset=str(dataset),
        repo_path=str(repo),
        snapshot_sha=resolve_snapshot_sha(repo),
        strategy="hybrid" if use_llm else "deterministic",
        body_chars=body_chars,
        max_results_per_keyword=settings.max_search_results,
        ranking=ranking,
        at_base=at_base,
        metrics=aggregate(results),
        results=results,
    )

    out.mkdir(parents=True, exist_ok=True)
    dataset_tag = Path(dataset).stem.replace("-issues", "")
    suffix = "-base" if at_base else ""
    stem = f"{dataset_tag}{suffix}-{run.strategy}-body{body_chars}-{ranking}"
    (out / f"{stem}.json").write_text(json.dumps(run.as_dict(), indent=2), encoding="utf-8")
    (out / f"{stem}.md").write_text(render_markdown(run), encoding="utf-8")

    for key, value in run.metrics.items():
        typer.echo(f"{key}={value:.3f}")
    typer.echo(f"report={out / f'{stem}.md'}")


if __name__ == "__main__":
    app()
