from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Runtime limits are explicit so safety and evaluation are reproducible."""

    state_dir: Path = Path(".repopilot")
    max_search_results: int = Field(default=30, ge=1, le=200)
    max_file_bytes: int = Field(default=200_000, ge=1_000, le=2_000_000)
    search_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    context_lines: int = Field(default=3, ge=0, le=20)

    def resolve_state_dir(self, project_root: Path) -> Path:
        path = self.state_dir
        if not path.is_absolute():
            path = project_root / path
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()
