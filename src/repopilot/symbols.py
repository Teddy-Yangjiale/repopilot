"""tree-sitter based symbol refinement: map a text hit to its enclosing function.

This is the first step of upgrading "text hit" into "call path": when a keyword hits
a line, the enclosing function's *name* is the symbol a caller would reference. By
feeding that name back into the text search we recall the callers without building a
full cross-file call graph (which would require parsing the whole tree and is broken
by C++ macros/templates anyway).

The import is lazy and cached: without the optional `symbols` extra the feature simply
degrades to no-op, so the deterministic baseline keeps its zero-heavy-dependency path.
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


def enclosing_function(path: Path, line: int) -> FunctionDef | None:
    """Return the innermost function_definition containing `line` (1-based), or None.

    Returns None when the grammar is unavailable (optional extra not installed), the
    file cannot be read, or the line does not fall inside any function definition.
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
    root = tree.root_node

    best: FunctionDef | None = None

    def walk(node) -> None:
        nonlocal best
        start = node.start_point[0] + 1
        end = node.end_point[0] + 1
        if node.type == "function_definition" and start <= line <= end:
            name = _function_name(node)
            if name:
                best = FunctionDef(name=name, line_start=start, line_end=end)
        for child in node.children:
            walk(child)

    walk(root)
    return best


def _function_name(node) -> str | None:
    declarator = node.child_by_field_name("declarator")
    if declarator is None:
        return None
    # `declarator` is the outer (possibly pointer/qualified) declarator; its own
    # `declarator` field carries the identifier for a plain function.
    identifier = declarator.child_by_field_name("declarator")
    target = identifier if identifier is not None else declarator
    text = target.text.decode("utf-8", "replace")
    # Strip parameter lists / trailing qualifiers defensively.
    text = text.split("(")[0].split(" ")[-1]
    return text or None
