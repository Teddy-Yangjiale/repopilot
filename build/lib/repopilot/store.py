from __future__ import annotations

import sqlite3
from pathlib import Path

from repopilot.models import TaskState


class TaskStore:
    """SQLite is enough for one-user local durability and keeps checkpoints queryable."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    question TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save(self, state: TaskState) -> None:
        payload = state.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks(task_id, stage, repo_path, question, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    stage = excluded.stage,
                    repo_path = excluded.repo_path,
                    question = excluded.question,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    state.task_id,
                    state.stage.value,
                    str(state.repo_path),
                    state.question,
                    payload,
                    state.updated_at.isoformat(),
                ),
            )

    def load(self, task_id: str) -> TaskState:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"task not found: {task_id}")
        return TaskState.model_validate_json(row["state_json"])

    def list(self, limit: int = 20) -> list[TaskState]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT state_json FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [TaskState.model_validate_json(row["state_json"]) for row in rows]
