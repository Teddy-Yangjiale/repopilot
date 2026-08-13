from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .base import Tool, ToolMetadata
from .path_policy import resolve_repo_root


@dataclass(frozen=True, slots=True)
class GitSnapshot:
    root: Path
    branch: str
    head: str
    dirty: bool


class GitInspector(Tool[Path, GitSnapshot]):
    metadata = ToolMetadata(
        name="git_inspector",
        description="Read repository root, branch, HEAD and dirty state.",
    )

    def run(self, repo_path: Path) -> GitSnapshot:
        root = resolve_repo_root(repo_path)

        def git(*args: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()

        return GitSnapshot(
            root=root,
            branch=git("branch", "--show-current") or "DETACHED",
            head=git("rev-parse", "HEAD"),
            dirty=bool(git("status", "--porcelain")),
        )
