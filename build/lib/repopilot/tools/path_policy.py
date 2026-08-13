from __future__ import annotations

from pathlib import Path


class PathPolicyError(ValueError):
    pass


def resolve_repo_root(repo_path: Path) -> Path:
    root = repo_path.expanduser().resolve()
    if not root.is_dir():
        raise PathPolicyError(f"repository path does not exist: {root}")
    if not (root / ".git").exists():
        raise PathPolicyError(f"not a Git repository: {root}")
    return root


def resolve_inside_repo(repo_root: Path, relative_path: str) -> Path:
    root = repo_root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PathPolicyError(f"path escapes repository: {relative_path}") from exc
    if not candidate.is_file():
        raise PathPolicyError(f"file does not exist: {relative_path}")
    return candidate
