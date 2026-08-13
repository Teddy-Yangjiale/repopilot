from __future__ import annotations

from repopilot.eval.mining_rest import CLOSES_RE


def test_closes_regex_extracts_issue_number() -> None:
    assert CLOSES_RE.search("Fixes #1234").group(1) == "1234"
    assert CLOSES_RE.search("closes #42 in favor of the new API").group(1) == "42"
    assert CLOSES_RE.search("resolves  #99").group(1) == "99"
    assert CLOSES_RE.search("no reference here") is None


def test_mine_dataset_rest_builds_case_from_merged_pr(monkeypatch) -> None:
    import repopilot.eval.mining_rest as mr

    responses = {
        "repos/o/r/pulls?state=closed&per_page=100&page=1": [
            # merged, references issue 10, one source + one doc file changed
            {
                "number": 5, "merged_at": "2026-01-01T00:00:00Z",
                "body": "Fixes #10", "base": {"sha": "abc"},
            },
            # not merged -> skipped
            {"number": 6, "merged_at": None, "body": "Fixes #11", "base": {"sha": "def"}},
            # merged but no closes reference -> counted as no_closes_ref
            {
                "number": 7, "merged_at": "2026-01-01T00:00:00Z",
                "body": "no reference", "base": {"sha": "ghi"},
            },
        ],
        "repos/o/r/issues/10": {
            "number": 10,
            "title": "bug in parser",
            "body": "x" * 100,
            "created_at": "2026-01-01T00:00:00Z",
            "html_url": "https://example.invalid/10",
        },
        "repos/o/r/pulls/5/files?per_page=100": [
            {"filename": "src/a.py"},
            {"filename": "docs/readme.md"},
        ],
    }

    def fake_api(endpoint, timeout):
        return responses.get(endpoint, [])  # empty page -> mining loop stops

    monkeypatch.setattr(mr, "_gh_api", fake_api)

    result = mr.mine_dataset_rest("o/r", {"src/a.py"}, limit=10, max_changed_files=10)

    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.issue_number == 10
    assert case.gold_files == ["src/a.py"]  # docs filtered by SOURCE_SUFFIXES
    assert case.pr_number == 5
    assert case.base_sha == "abc"
    assert result.stats.accepted == 1
    assert result.stats.no_closes_ref == 1  # PR 7
