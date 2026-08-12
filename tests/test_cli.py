from pathlib import Path

from typer.testing import CliRunner

import repopilot.cli as cli_module
from repopilot.cli import app
from repopilot.query_expansion import LLMConfigurationError


class MissingKeyOrchestrator:
    def create_task(
        self,
        repo: Path,
        question: str,
        keywords: list[str] | None,
        use_llm: bool,
    ) -> object:
        return object()

    def run(self, state: object) -> None:
        raise LLMConfigurationError("LLM_API_KEY is missing")


def test_cli_renders_llm_configuration_error_without_traceback(
    sample_repo: Path, monkeypatch
) -> None:
    monkeypatch.setattr(cli_module, "get_orchestrator", lambda: MissingKeyOrchestrator())

    result = CliRunner().invoke(
        app,
        [
            "investigate",
            "--repo",
            str(sample_repo),
            "--question",
            "How does ReActAgent stop?",
            "--use-llm",
        ],
    )

    assert result.exit_code == 2
    assert result.output == "Configuration error: LLM_API_KEY is missing\n"
    assert "Traceback" not in result.output
