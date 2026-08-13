from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .base import Tool, ToolMetadata
from .path_policy import resolve_inside_repo, resolve_repo_root


@dataclass(frozen=True, slots=True)
class ReadRequest:
    repo_path: Path
    relative_path: str
    line_start: int = 1
    line_end: int = 200


class SafeFileReader(Tool[ReadRequest, str]):
    metadata = ToolMetadata(
        name="safe_file_reader",
        description="Read a bounded line range from a file inside the repository.",
    )

    def __init__(self, max_file_bytes: int = 200_000) -> None:
        self.max_file_bytes = max_file_bytes

    def run(self, request: ReadRequest) -> str:
        root = resolve_repo_root(request.repo_path)
        path = resolve_inside_repo(root, request.relative_path)
        if path.stat().st_size > self.max_file_bytes:
            raise ValueError(f"file exceeds {self.max_file_bytes} bytes: {request.relative_path}")
        if request.line_start < 1 or request.line_end < request.line_start:
            raise ValueError("invalid line range")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = lines[request.line_start - 1 : request.line_end]
        return "\n".join(
            f"{number}: {line}"
            for number, line in enumerate(selected, start=request.line_start)
        )

    def find_lines(
        self, repo_path: Path, relative_path: str, keyword: str, limit: int = 20
    ) -> list[int]:
        """Locate a focus term safely when issue line numbers have drifted."""

        root = resolve_repo_root(repo_path)
        path = resolve_inside_repo(root, relative_path)
        if path.stat().st_size > self.max_file_bytes:
            raise ValueError(f"file exceeds {self.max_file_bytes} bytes: {relative_path}")
        needle = keyword.casefold()
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return [
            number
            for number, line in enumerate(lines, start=1)
            if needle in line.casefold()
        ][:limit]
