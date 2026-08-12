from pathlib import Path

import pytest

from repopilot.tools.path_policy import PathPolicyError, resolve_inside_repo
from repopilot.tools.read_tools import ReadRequest, SafeFileReader
from repopilot.tools.search_tools import CodeSearchTool, SearchRequest


def test_search_returns_line_level_evidence(sample_repo: Path) -> None:
    result = CodeSearchTool().run(SearchRequest(sample_repo, "invoke_with_tools"))
    assert result
    assert result[0].path == "agent.py"
    assert result[0].line_start == 1
    assert result[0].line_end == 5
    assert "3:         response = self.invoke_with_tools()" in result[0].snippet
    assert all("__pycache__" not in item.path for item in result)


def test_reader_rejects_path_escape(sample_repo: Path) -> None:
    with pytest.raises(PathPolicyError):
        resolve_inside_repo(sample_repo, "../outside.txt")


def test_reader_returns_numbered_lines(sample_repo: Path) -> None:
    text = SafeFileReader().run(ReadRequest(sample_repo, "agent.py", 2, 4))
    assert "3:         response = self.invoke_with_tools()" in text
