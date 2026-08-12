from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    (repo / "agent.py").write_text(
        "class ReActAgent:\n"
        "    def run(self):\n"
        "        response = self.invoke_with_tools()\n"
        "        if response == 'Finish':\n"
        "            return 'done'\n",
        encoding="utf-8",
    )
    cache = repo / "__pycache__"
    cache.mkdir()
    (cache / "agent.pyc").write_bytes(b"ReActAgent invoke_with_tools Finish")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "agent.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=RepoPilot Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )
    return repo
