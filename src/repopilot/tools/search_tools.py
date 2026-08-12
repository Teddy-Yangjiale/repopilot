from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from repopilot.models import Evidence

from .base import Tool, ToolMetadata
from .path_policy import resolve_repo_root


@dataclass(frozen=True, slots=True)
class SearchRequest:
    repo_path: Path
    keyword: str
    limit: int = 30
    context_lines: int = 3
    timeout_seconds: float = 10.0


class CodeSearchTool(Tool[SearchRequest, list[Evidence]]):
    metadata = ToolMetadata(
        name="code_search",
        description="Search source files and return line-level evidence.",
    )

    def run(self, request: SearchRequest) -> list[Evidence]:
        root = resolve_repo_root(request.repo_path)
        keyword = request.keyword.strip()
        if not keyword:
            return []
        if shutil.which("rg"):
            return self._search_with_rg(root, request)
        return self._search_with_python(root, request)

    def _search_with_rg(self, root: Path, request: SearchRequest) -> list[Evidence]:
        command = [
            "rg",
            "--line-number",
            "--column",
            "--no-heading",
            "--color",
            "never",
            "--fixed-strings",
            "--glob",
            "!.git/**",
            "--glob",
            "!**/__pycache__/**",
            "--glob",
            "!.venv/**",
            "--glob",
            "!*.py[co]",
            "--glob",
            "!*.lock",
            request.keyword,
            str(root),
        ]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip() or "rg search failed")

        evidence: list[Evidence] = []
        for line in result.stdout.splitlines()[: request.limit]:
            match = re.match(r"^(.*?):(\d+):(\d+):(.*)$", line)
            if not match:
                continue
            absolute, line_number, _, snippet = match.groups()
            relative = Path(absolute).resolve().relative_to(root).as_posix()
            number = int(line_number)
            evidence.append(
                self._build_evidence(
                    root=root,
                    relative_path=relative,
                    line_number=number,
                    fallback_snippet=snippet,
                    keyword=request.keyword,
                    context_lines=request.context_lines,
                )
            )
        return evidence

    def _search_with_python(self, root: Path, request: SearchRequest) -> list[Evidence]:
        evidence: list[Evidence] = []
        for path in root.rglob("*"):
            if len(evidence) >= request.limit:
                break
            if (
                not path.is_file()
                or any(part in {".git", ".venv", "__pycache__"} for part in path.parts)
                or path.suffix in {".pyc", ".pyo"}
                or path.stat().st_size > 1_000_000
            ):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, 1):
                if request.keyword in line:
                    evidence.append(
                        self._build_evidence(
                            root=root,
                            relative_path=path.relative_to(root).as_posix(),
                            line_number=line_number,
                            fallback_snippet=line,
                            keyword=request.keyword,
                            context_lines=request.context_lines,
                        )
                    )
                    if len(evidence) >= request.limit:
                        break
        return evidence

    def _build_evidence(
        self,
        root: Path,
        relative_path: str,
        line_number: int,
        fallback_snippet: str,
        keyword: str,
        context_lines: int,
    ) -> Evidence:
        path = root / relative_path
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            line_start = max(1, line_number - context_lines)
            line_end = min(len(lines), line_number + context_lines)
            selected = lines[line_start - 1 : line_end]
            snippet = "\n".join(
                f"{number}: {line}"
                for number, line in enumerate(selected, start=line_start)
            )
        except OSError:
            line_start = line_number
            line_end = line_number
            snippet = fallback_snippet.strip()

        return Evidence(
            path=relative_path,
            line_start=line_start,
            line_end=line_end,
            snippet=snippet[:2_000],
            keyword=keyword,
        )
