from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    name: str
    description: str
    read_only: bool = True


class Tool(ABC, Generic[InputT, OutputT]):
    """Small tool protocol; agents depend on this abstraction, not subprocess details."""

    metadata: ToolMetadata

    @abstractmethod
    def run(self, tool_input: InputT) -> OutputT:
        raise NotImplementedError
