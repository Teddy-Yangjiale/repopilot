from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from repopilot.models import Evidence

from .base import Tool, ToolMetadata
from .path_policy import resolve_repo_root

BINARY_SNIFF_BYTES = 8_192
MAX_SEARCHABLE_FILE_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class SearchRequest:
    repo_path: Path
    keyword: str
    limit: int = 30
    context_lines: int = 3
    timeout_seconds: float = 10.0
    max_per_file: int = 5


@dataclass(frozen=True, slots=True)
class FileMatches:
    path: str
    hit_lines: list[int]


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Evidence is truncated for citation; corpus statistics are not, because ranking needs them.

    `matches` covers every file containing the keyword and `corpus_files` is the scan denominator,
    which together are exactly what inverse document frequency requires. Returning only the
    truncated evidence — as this tool used to — throws that away and makes IDF impossible.
    """

    keyword: str
    corpus_files: int
    matches: list[FileMatches]
    evidence: list[Evidence]


def list_tracked_files(root: Path, timeout_seconds: float = 10.0) -> list[str]:
    """Only git-tracked files are evidence: they are the repository at a reproducible commit.

    Walking the working tree instead would pull in build outputs and other untracked noise,
    which silently dominated search results before this was git-scoped. `git ls-files` also
    gives a stable order, so truncating at a limit stays reproducible across machines.
    """

    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return [path for path in result.stdout.split("\0") if path]


class CodeSearchTool(Tool[SearchRequest, SearchResult]):
    """Literal substring search over tracked files; the baseline later phases are measured on."""

    metadata = ToolMetadata(
        name="code_search",
        description="Search git-tracked source files and return evidence plus corpus statistics.",
    )

    def run(self, request: SearchRequest) -> SearchResult:
        root = resolve_repo_root(request.repo_path)
        keyword = request.keyword.strip()
        if not keyword:
            return SearchResult(keyword=keyword, corpus_files=0, matches=[], evidence=[])

        matches, corpus_files = self._scan(root, keyword, request.timeout_seconds)
        # Ranking the whole repository before truncating is the point: stopping the scan early
        # would return whichever files `git ls-files` happens to list first, which is alphabetical
        # order, not relevance. Path is the tiebreaker so equal-scoring files stay reproducible.
        matches.sort(key=lambda match: (-len(match.hit_lines), match.path))

        evidence: list[Evidence] = []
        for match in matches:
            if len(evidence) >= request.limit:
                break
            lines = self._read_text_lines(root / match.path)
            if lines is None:
                continue
            for line_number in match.hit_lines[: request.max_per_file]:
                if len(evidence) >= request.limit:
                    break
                evidence.append(
                    self._build_evidence(
                        lines=lines,
                        relative_path=match.path,
                        line_number=line_number,
                        keyword=keyword,
                        context_lines=request.context_lines,
                    )
                )
        return SearchResult(
            keyword=keyword,
            corpus_files=corpus_files,
            matches=matches,
            evidence=evidence,
        )

    def _scan(
        self, root: Path, keyword: str, timeout_seconds: float
    ) -> tuple[list[FileMatches], int]:
        """First pass records where the keyword occurs; snippets are built later for kept files.

        Also counts how many files were actually searched. That count is the IDF denominator, and
        it must exclude binaries and oversized files or a keyword's rarity would be overstated.
        """

        matches: list[FileMatches] = []
        corpus_files = 0
        for relative_path in list_tracked_files(root, timeout_seconds):
            lines = self._read_text_lines(root / relative_path)
            if lines is None:
                continue
            corpus_files += 1
            hit_lines = [number for number, line in enumerate(lines, 1) if keyword in line]
            if hit_lines:
                matches.append(FileMatches(path=relative_path, hit_lines=hit_lines))
        return matches, corpus_files

    def _read_text_lines(self, path: Path) -> list[str] | None:
        """Returns None for anything not searchable: oversized, unreadable or binary."""

        try:
            if path.stat().st_size > MAX_SEARCHABLE_FILE_BYTES:
                return None
            raw = path.read_bytes()
        except OSError:
            return None
        if b"\0" in raw[:BINARY_SNIFF_BYTES]:
            return None
        return raw.decode("utf-8", errors="replace").splitlines()

    def _build_evidence(
        self,
        lines: list[str],
        relative_path: str,
        line_number: int,
        keyword: str,
        context_lines: int,
    ) -> Evidence:
        line_start = max(1, line_number - context_lines)
        line_end = min(len(lines), line_number + context_lines)
        selected = lines[line_start - 1 : line_end]
        snippet = "\n".join(
            f"{number}: {line}" for number, line in enumerate(selected, start=line_start)
        )
        return Evidence(
            path=relative_path,
            line_start=line_start,
            line_end=line_end,
            snippet=snippet[:2_000],
            keyword=keyword,
        )
