"""REST-based dataset mining for repos whose GraphQL search returns nothing.

`facebook/react`'s GraphQL search returns 0 nodes even for `repo:facebook/react` (a
GitHub index limitation), while its REST API works normally. This backend mines
closed+merged pull requests, reads the `fixes|closes|resolves #N` reference in the PR
body to recover the linked issue, and takes the PR's changed files as the gold set —
mirroring `mine_dataset`'s filtering rules.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from repopilot.eval.dataset import EvalCase
from repopilot.eval.mining import (
    SOURCE_SUFFIXES,
    DatasetMiningError,
    MiningResult,
)

CLOSES_RE = re.compile(r"\b(?:fixes|closes|resolves)\s+#(\d+)", re.IGNORECASE)


def _gh_api(endpoint: str, timeout_seconds: float) -> dict | list:
    """Run `gh api` and return parsed JSON; auth stays in the user's gh session."""
    try:
        completed = subprocess.run(
            ["gh", "api", endpoint],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise DatasetMiningError(
            "gh CLI not found. Install GitHub CLI and run `gh auth login`."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise DatasetMiningError(f"gh api failed: {exc.stderr.strip()[:300]}") from exc
    return json.loads(completed.stdout)


def mine_dataset_rest(
    repo: str,
    tracked_files: set[str],
    limit: int = 50,
    max_changed_files: int = 10,
    min_body_chars: int = 80,
    timeout_seconds: float = 60.0,
) -> MiningResult:
    """Build localization cases from merged PRs that reference a closing issue."""

    result = MiningResult()
    seen_prs: set[int] = set()
    seen_issues: set[int] = set()
    page = 1
    max_pages = 50  # guard: closed-PR lists can be huge; newest come first

    while len(result.cases) < limit and page <= max_pages:
        prs = _gh_api(
            f"repos/{repo}/pulls?state=closed&per_page=100&page={page}",
            timeout_seconds,
        )
        if not isinstance(prs, list) or not prs:
            break
        for pr in prs:
            if len(result.cases) >= limit:
                break
            if not isinstance(pr, dict) or not pr.get("merged_at"):
                continue
            if pr.get("number") in seen_prs:
                continue
            result.stats.issues_examined += 1

            body = pr.get("body") or ""
            reference = CLOSES_RE.search(body)
            if reference is None:
                result.stats.no_closes_ref += 1
                continue
            issue_number = int(reference.group(1))
            if issue_number in seen_issues:
                result.stats.duplicate_pr += 1
                continue

            issue = _gh_api(f"repos/{repo}/issues/{issue_number}", timeout_seconds)
            if not isinstance(issue, dict) or "pull_request" in issue:
                continue  # the reference actually points at another PR
            issue_body = issue.get("body") or ""
            if len(issue_body) < min_body_chars:
                result.stats.body_too_short += 1
                continue

            files = _gh_api(
                f"repos/{repo}/pulls/{pr['number']}/files?per_page=100",
                timeout_seconds,
            )
            if not isinstance(files, list):
                continue
            changed = [entry["filename"] for entry in files if isinstance(entry, dict)]
            if len(changed) > max_changed_files:
                result.stats.too_many_files += 1
                continue
            gold = [path for path in changed if Path(path).suffix.lower() in SOURCE_SUFFIXES]
            if not gold:
                result.stats.no_source_files += 1
                continue

            missing = [path for path in gold if path not in tracked_files]
            if missing:
                result.stats.gold_missing_at_snapshot += 1
                continue

            haystack = f"{issue.get('title', '')}\n{issue_body}".lower()
            mentions = any(
                path.lower() in haystack or Path(path).name.lower() in haystack
                for path in gold
            )

            result.cases.append(
                EvalCase(
                    case_id=f"{repo.replace('/', '-')}-{issue_number}",
                    repo=repo,
                    issue_number=issue_number,
                    issue_url=issue.get("html_url", ""),
                    title=issue.get("title", ""),
                    body=issue_body,
                    created_at=issue.get("created_at", ""),
                    pr_number=pr["number"],
                    base_sha=(pr.get("base") or {}).get("sha", ""),
                    gold_files=sorted(gold),
                    changed_files_total=len(changed),
                    body_mentions_gold_path=mentions,
                )
            )
            result.stats.accepted += 1
            seen_prs.add(pr["number"])
            seen_issues.add(issue_number)
        page += 1

    return result
