from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from repopilot.eval.dataset import EvalCase

SOURCE_SUFFIXES = frozenset(
    {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx", ".cu", ".cl",
     ".py", ".java", ".js", ".m", ".mm", ".kt", ".rs", ".go"}
)

SEARCH_QUERY = """
query($q: String!, $cursor: String) {
  search(query: $q, type: ISSUE, first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on Issue {
        number title bodyText url createdAt
        closedByPullRequestsReferences(first: 3, includeClosedPrs: true) {
          nodes {
            number merged baseRefOid
            files(first: 100) { totalCount nodes { path } }
          }
        }
      }
    }
  }
}
"""


class DatasetMiningError(RuntimeError):
    """Raised when the GitHub dataset cannot be built; never silently produces a partial set."""


@dataclass
class MiningStats:
    """Why issues were discarded. A dataset nobody can audit is not evidence of anything."""

    issues_examined: int = 0
    no_merged_pr: int = 0
    too_many_files: int = 0
    no_source_files: int = 0
    body_too_short: int = 0
    duplicate_pr: int = 0
    gold_missing_at_snapshot: int = 0
    accepted: int = 0

    def as_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


@dataclass
class MiningResult:
    cases: list[EvalCase] = field(default_factory=list)
    stats: MiningStats = field(default_factory=MiningStats)


def mine_dataset(
    repo: str,
    tracked_files: set[str],
    limit: int = 50,
    max_changed_files: int = 10,
    min_body_chars: int = 80,
    timeout_seconds: float = 60.0,
) -> MiningResult:
    """Build localization cases from closed issues that a merged pull request fixed."""

    result = MiningResult()
    seen_prs: set[int] = set()
    cursor: str | None = None
    query = f"repo:{repo} is:issue is:closed linked:pr sort:created-desc"

    while len(result.cases) < limit:
        page = _graphql(SEARCH_QUERY, {"q": query, "cursor": cursor}, timeout_seconds)
        search = page["search"]
        for node in search["nodes"]:
            if not node:
                continue
            result.stats.issues_examined += 1
            case = _build_case(repo, node, tracked_files, seen_prs, result.stats,
                               max_changed_files, min_body_chars)
            if case is not None:
                result.cases.append(case)
                result.stats.accepted += 1
                seen_prs.add(case.pr_number)
            if len(result.cases) >= limit:
                break

        if not search["pageInfo"]["hasNextPage"]:
            break
        cursor = search["pageInfo"]["endCursor"]

    return result


def _build_case(
    repo: str,
    node: dict,
    tracked_files: set[str],
    seen_prs: set[int],
    stats: MiningStats,
    max_changed_files: int,
    min_body_chars: int,
) -> EvalCase | None:
    body = node.get("bodyText") or ""
    if len(body) < min_body_chars:
        stats.body_too_short += 1
        return None

    pull_request = next(
        (pr for pr in node["closedByPullRequestsReferences"]["nodes"] if pr and pr["merged"]),
        None,
    )
    if pull_request is None:
        stats.no_merged_pr += 1
        return None
    if pull_request["number"] in seen_prs:
        stats.duplicate_pr += 1
        return None

    changed_total = pull_request["files"]["totalCount"]
    if changed_total > max_changed_files:
        # A 40-file refactor is not a localization task; nobody could rank it meaningfully.
        stats.too_many_files += 1
        return None

    changed = [entry["path"] for entry in pull_request["files"]["nodes"]]
    gold = [path for path in changed if Path(path).suffix.lower() in SOURCE_SUFFIXES]
    if not gold:
        stats.no_source_files += 1
        return None

    missing = [path for path in gold if path not in tracked_files]
    if missing:
        # The file was renamed or deleted after the fix, so no retriever could return it today.
        stats.gold_missing_at_snapshot += 1
        return None

    haystack = f"{node['title']}\n{body}".lower()
    mentions = any(
        path.lower() in haystack or Path(path).name.lower() in haystack for path in gold
    )

    return EvalCase(
        case_id=f"{repo.replace('/', '-')}-{node['number']}",
        repo=repo,
        issue_number=node["number"],
        issue_url=node["url"],
        title=node["title"],
        body=body,
        created_at=node["createdAt"],
        pr_number=pull_request["number"],
        base_sha=pull_request["baseRefOid"],
        gold_files=sorted(gold),
        changed_files_total=changed_total,
        body_mentions_gold_path=mentions,
    )


def _graphql(query: str, variables: dict[str, str | None], timeout_seconds: float) -> dict:
    """Shells out to `gh` so auth stays in the user's existing session, not in our config."""

    command = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is not None:
            command += ["-f", f"{key}={value}"]

    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=timeout_seconds
        )
    except FileNotFoundError as exc:
        raise DatasetMiningError(
            "gh CLI not found. Install GitHub CLI and run `gh auth login`."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise DatasetMiningError(f"gh api failed: {exc.stderr.strip()[:300]}") from exc

    payload = json.loads(completed.stdout)
    if payload.get("errors"):
        raise DatasetMiningError(f"GraphQL errors: {payload['errors']}")
    return payload["data"]
