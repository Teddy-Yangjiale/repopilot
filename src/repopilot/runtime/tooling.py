from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from repopilot.models import Evidence
from repopilot.runtime.models import ToolObservation
from repopilot.tools import CodeSearchTool, SafeFileReader
from repopilot.tools.read_tools import ReadRequest
from repopilot.tools.search_tools import SearchRequest


class ToolExecutionError(RuntimeError):
    pass


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        min_length=3,
        max_length=300,
        description="Brief reason this action is the best next step; no hidden reasoning.",
    )


class SearchCodeArguments(ToolArguments):
    keyword: str = Field(min_length=2, max_length=120)


class ReadFileArguments(ToolArguments):
    path: str = Field(min_length=1, max_length=500)
    line_start: int = Field(default=1, ge=1)
    line_end: int = Field(default=200, ge=1)
    focus_keyword: str = Field(min_length=2, max_length=120)


class GitHistoryArguments(ToolArguments):
    path: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class FinishArguments(ToolArguments):
    answer: str = Field(min_length=20, max_length=12_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)


class RuntimeTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    arguments_model: ClassVar[type[ToolArguments]]

    def schema(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }

    def validate(self, arguments: dict[str, object]) -> ToolArguments:
        try:
            return self.arguments_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolExecutionError(f"invalid arguments for {self.name}: {exc}") from exc

    @abstractmethod
    def execute(self, repo_path: Path, arguments: ToolArguments) -> ToolObservation:
        raise NotImplementedError


class SearchCodeRuntimeTool(RuntimeTool):
    name = "search_code"
    description = (
        "Search all git-tracked files for a literal code symbol or technical term. "
        "Use this to discover candidate files and line-level evidence."
    )
    arguments_model = SearchCodeArguments

    def __init__(self, search_tool: CodeSearchTool | None = None) -> None:
        self.search_tool = search_tool or CodeSearchTool()

    def execute(self, repo_path: Path, arguments: ToolArguments) -> ToolObservation:
        assert isinstance(arguments, SearchCodeArguments)
        result = self.search_tool.run(
            SearchRequest(
                repo_path=repo_path,
                keyword=arguments.keyword,
                limit=30,
                context_lines=3,
                timeout_seconds=10,
            )
        )
        ranked = sorted(result.matches, key=lambda item: (-len(item.hit_lines), item.path))[:15]
        content = "\n".join(
            f"{item.path}: {len(item.hit_lines)} hit(s), first lines {item.hit_lines[:5]}"
            for item in ranked
        ) or "No tracked file matched the keyword."
        return ToolObservation(
            content=content,
            evidence=result.evidence,
            metadata={
                "keyword": arguments.keyword,
                "matched_files": len(result.matches),
                "corpus_files": result.corpus_files,
            },
        )


class ReadFileRuntimeTool(RuntimeTool):
    name = "read_file"
    description = (
        "Read a bounded line range from one repository file. The focus_keyword must "
        "appear in the requested range so the observation can become verifiable evidence."
    )
    arguments_model = ReadFileArguments

    def __init__(self, reader: SafeFileReader | None = None) -> None:
        self.reader = reader or SafeFileReader()

    def execute(self, repo_path: Path, arguments: ToolArguments) -> ToolObservation:
        assert isinstance(arguments, ReadFileArguments)
        if arguments.line_end < arguments.line_start:
            raise ToolExecutionError("line_end must be greater than or equal to line_start")
        if arguments.line_end - arguments.line_start > 300:
            raise ToolExecutionError("a read_file action may read at most 301 lines")
        content = self.reader.run(
            ReadRequest(
                repo_path=repo_path,
                relative_path=arguments.path,
                line_start=arguments.line_start,
                line_end=arguments.line_end,
            )
        )
        if arguments.focus_keyword.casefold() not in content.casefold():
            raise ToolExecutionError(
                f"focus_keyword {arguments.focus_keyword!r} is absent from the requested range"
            )
        actual_line_count = len(content.splitlines())
        actual_line_end = arguments.line_start + max(0, actual_line_count - 1)
        evidence = Evidence(
            path=arguments.path,
            line_start=arguments.line_start,
            line_end=actual_line_end,
            snippet=content,
            keyword=arguments.focus_keyword,
            source="agent_read_file",
        )
        return ToolObservation(content=content, evidence=[evidence])


class GitHistoryRuntimeTool(RuntimeTool):
    name = "git_history"
    description = (
        "Read recent commits that changed one repository path. Use only after code evidence "
        "suggests history can clarify intent; this tool never changes the repository."
    )
    arguments_model = GitHistoryArguments

    def execute(self, repo_path: Path, arguments: ToolArguments) -> ToolObservation:
        assert isinstance(arguments, GitHistoryArguments)
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "log",
                f"-{arguments.limit}",
                "--format=%h %cs %s",
                "--",
                arguments.path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return ToolObservation(
            content=completed.stdout.strip() or "No commit history found for this path.",
            metadata={"path": arguments.path, "limit": arguments.limit},
        )


class FinishRuntimeTool(RuntimeTool):
    name = "finish"
    description = (
        "Finish only when the answer is supported by collected evidence IDs. Explain the "
        "code path and limitations; never claim runtime behavior from text matches alone."
    )
    arguments_model = FinishArguments

    def execute(self, repo_path: Path, arguments: ToolArguments) -> ToolObservation:
        assert isinstance(arguments, FinishArguments)
        return ToolObservation(
            content=arguments.answer,
            metadata={"evidence_ids": arguments.evidence_ids},
        )


class ToolRegistry:
    def __init__(self, tools: list[RuntimeTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("runtime tool names must be unique")

    @classmethod
    def readonly_default(cls) -> ToolRegistry:
        return cls(
            [
                SearchCodeRuntimeTool(),
                ReadFileRuntimeTool(),
                GitHistoryRuntimeTool(),
                FinishRuntimeTool(),
            ]
        )

    @property
    def schemas(self) -> list[dict[str, object]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(
        self, name: str, repo_path: Path, arguments: dict[str, object]
    ) -> ToolObservation:
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(sorted(self._tools))
            raise ToolExecutionError(f"unknown tool {name!r}; available: {available}")
        validated = tool.validate(arguments)
        return tool.execute(repo_path, validated)

    def fingerprint(self, name: str, arguments: dict[str, object]) -> str:
        comparable = {key: value for key, value in arguments.items() if key != "reason"}
        return f"{name}:{json.dumps(comparable, sort_keys=True, ensure_ascii=True)}"
