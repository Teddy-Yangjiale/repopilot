"""tree-sitter based symbol refinement: map a text hit to its enclosing function.

Two capabilities over the C++ grammar:

- `enclosing_function`: the function a hit line sits inside (its *name* is the symbol
  callers reference).
- `classify_hit_line`: whether a hit line is part of a function **signature** (a
  definition hit — the fix location) or inside its body (a use/implementation hit).

The latter is the signal that matters for localization: a keyword hitting a function
signature means the file *defines* that symbol, whereas a body hit means it merely
mentions/implements it. Caller-recall (re-searching the name) was measured negative,
so the definition-vs-use weighting is the successor.

The import is lazy and cached: without the optional `symbols` extra the feature degrades
to no-op, keeping the deterministic baseline's zero-heavy-dependency path.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class FunctionDef:
    name: str
    line_start: int
    line_end: int


@lru_cache(maxsize=1)
def _cpp_parser():
    """Cached tree-sitter C++ parser; ImportError propagates to the caller."""
    import tree_sitter_cpp
    from tree_sitter import Language, Parser

    return Parser(Language(tree_sitter_cpp.language()))


def _find_function_node(root, line: int):
    """Innermost function_definition node containing `line`, or None."""
    best = None

    def walk(node):
        nonlocal best
        start = node.start_point[0] + 1
        end = node.end_point[0] + 1
        if node.type == "function_definition" and start <= line <= end:
            best = node
        for child in node.children:
            walk(child)

    walk(root)
    return best


def _function_name(node) -> str | None:
    declarator = node.child_by_field_name("declarator")
    if declarator is None:
        return None
    identifier = declarator.child_by_field_name("declarator")
    target = identifier if identifier is not None else declarator
    text = target.text.decode("utf-8", "replace")
    text = text.split("(")[0].split(" ")[-1]
    return text or None


def enclosing_function(path: Path, line: int) -> FunctionDef | None:
    """Return the innermost function_definition containing `line` (1-based), or None."""

    try:
        parser = _cpp_parser()
    except ImportError:
        return None
    try:
        source = path.read_bytes()
    except OSError:
        return None
    tree = parser.parse(source)
    node = _find_function_node(tree.root_node, line)
    if node is None:
        return None
    name = _function_name(node)
    if not name:
        return None
    return FunctionDef(
        name=name,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
    )


def classify_hit_line(path: Path, line: int) -> str | None:
    """Return "definition" if `line` is a function signature line, "use" if in a body.

    A signature line (from the function's start up to, but excluding, its body) is where
    the symbol is *declared/defined*; a body line is where it is implemented or another
    symbol is called. Returns None when the grammar is unavailable, the file unreadable,
    or the line is not inside any function definition.
    """

    try:
        parser = _cpp_parser()
    except ImportError:
        return None
    try:
        source = path.read_bytes()
    except OSError:
        return None
    tree = parser.parse(source)
    node = _find_function_node(tree.root_node, line)
    if node is None:
        return None
    body = node.child_by_field_name("body")
    if body is None:
        return "definition"  # a declaration without a body
    return "definition" if line <= body.start_point[0] + 1 else "use"


@lru_cache(maxsize=256)
def _file_spans(path_str: str) -> tuple[tuple[int, int | None, int], ...] | None:
    """Parse `path_str` once and return its function spans; None if unavailable.

    Spans are (start, body_start_or_None, end). The cache makes the tree-sitter pass
    cheap when the same file is hit by several keywords during one evaluation run.
    """
    try:
        parser = _cpp_parser()
    except ImportError:
        return None
    try:
        source = Path(path_str).read_bytes()
    except OSError:
        return None
    tree = parser.parse(source)

    spans: list[tuple[int, int | None, int]] = []

    def collect(node) -> None:
        if node.type == "function_definition":
            body = node.child_by_field_name("body")
            body_start = body.start_point[0] + 1 if body is not None else None
            spans.append((node.start_point[0] + 1, body_start, node.end_point[0] + 1))
        for child in node.children:
            collect(child)

    collect(tree.root_node)
    return tuple(spans)


def classify_lines(path: Path, lines: list[int]) -> dict[int, str | None]:
    """Classify multiple lines of one file (spans are cached per path).

    Returns a mapping line -> "definition" | "use" | None (None for lines outside any
    function, or when the grammar is unavailable / file unreadable).
    """

    result: dict[int, str | None] = {line: None for line in lines}
    spans = _file_spans(str(path))
    if spans is None:
        return result
    for line in lines:
        for start, body_start, end in spans:
            if start <= line <= end:
                if body_start is None or line <= body_start:
                    result[line] = "definition"
                else:
                    result[line] = "use"
                break
    return result
