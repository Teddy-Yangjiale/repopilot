from __future__ import annotations

import sqlite3
from pathlib import Path

from repopilot.runtime.models import AgentRun


class AgentRunStore:
    """Step-level durable state; one upsert occurs after every Action/Observation pair."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    question TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def save(self, run: AgentRun) -> None:
        run.touch()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs(run_id, status, repo_path, question, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    run.run_id,
                    run.status.value,
                    str(run.repo_path),
                    run.question,
                    run.model_dump_json(),
                    run.updated_at.isoformat(),
                ),
            )

    def load(self, run_id: str) -> AgentRun:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"agent run not found: {run_id}")
        return AgentRun.model_validate_json(row["state_json"])
