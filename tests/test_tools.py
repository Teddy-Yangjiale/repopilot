from pathlib import Path

import pytest

from repopilot.tools.path_policy import PathPolicyError, resolve_inside_repo
from repopilot.tools.read_tools import ReadRequest, SafeFileReader
from repopilot.tools.search_tools import CodeSearchTool, SearchRequest


def test_search_returns_line_level_evidence(sample_repo: Path) -> None:
    result = CodeSearchTool().run(SearchRequest(sample_repo, "invoke_with_tools")).evidence
    assert result
    assert result[0].path == "agent.py"
    assert result[0].line_start == 1
    assert result[0].line_end == 5
    assert "3:         response = self.invoke_with_tools()" in result[0].snippet
    assert all("__pycache__" not in item.path for item in result)


def test_search_ignores_untracked_files(sample_repo: Path) -> None:
    """Untracked build output silently dominated results before the scan was git-scoped."""
    (sample_repo / "build").mkdir()
    (sample_repo / "build" / "generated.cpp").write_text("invoke_with_tools\n" * 50, "utf-8")

    result = CodeSearchTool().run(SearchRequest(sample_repo, "invoke_with_tools")).evidence

    assert result
    assert all(item.path == "agent.py" for item in result)


def test_search_ranks_by_hit_count_not_filename_order(sample_repo: Path) -> None:
    """Truncating mid-scan used to return whatever `git ls-files` listed first: the alphabet."""
    (sample_repo / "aaa_rare.py").write_text("marker\n", "utf-8")
    (sample_repo / "zzz_common.py").write_text("marker\n" * 6, "utf-8")
    _commit_all(sample_repo)

    result = CodeSearchTool().run(SearchRequest(sample_repo, "marker", limit=10)).evidence

    assert [item.path for item in result][0] == "zzz_common.py"
    assert "aaa_rare.py" in {item.path for item in result}


def test_search_skips_binary_files(sample_repo: Path) -> None:
    (sample_repo / "blob.bin").write_bytes(b"\x00\x01marker\x00padding")
    _commit_all(sample_repo)

    assert CodeSearchTool().run(SearchRequest(sample_repo, "marker")).evidence == []


def test_search_scan_stops_at_deadline(sample_repo: Path, monkeypatch) -> None:
    """The timeout must bound the Python scan loop, not just the `git ls-files` call."""
    import repopilot.tools.search_tools as search_tools

    (sample_repo / "extra.cpp").write_text("marker\n", "utf-8")
    _commit_all(sample_repo)

    calls = {"count": 0}

    def fake_monotonic() -> float:
        calls["count"] += 1
        # First call computes the deadline; every later call is past it.
        return 100.0 if calls["count"] == 1 else 200.0

    monkeypatch.setattr(search_tools.time, "monotonic", fake_monotonic)

    result = search_tools.CodeSearchTool().run(
        search_tools.SearchRequest(sample_repo, "marker", timeout_seconds=1.0)
    )

    assert result.corpus_files == 0
    assert result.matches == []
    assert result.evidence == []


def _commit_all(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e.invalid",
         "commit", "-qm", "fixture"],
        check=True,
    )


def test_reader_rejects_path_escape(sample_repo: Path) -> None:
    with pytest.raises(PathPolicyError):
        resolve_inside_repo(sample_repo, "../outside.txt")


def test_reader_returns_numbered_lines(sample_repo: Path) -> None:
    text = SafeFileReader().run(ReadRequest(sample_repo, "agent.py", 2, 4))
    assert "3:         response = self.invoke_with_tools()" in text
