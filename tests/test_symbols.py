from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_cpp")

from repopilot.symbols import enclosing_function


def test_enclosing_function_locates_hit_line(tmp_path: Path) -> None:
    source = tmp_path / "a.cpp"
    source.write_text(
        "int helper(int x) { return x + 1; }\n"
        "\n"
        "void target_fn() {\n"
        "    helper(1);\n"
        "}\n",
        encoding="utf-8",
    )

    fn = enclosing_function(source, 4)  # the helper(1) call line

    assert fn is not None
    assert fn.name == "target_fn"
    assert fn.line_start == 3
    assert fn.line_end == 5


def test_enclosing_function_returns_none_outside_function(tmp_path: Path) -> None:
    source = tmp_path / "b.cpp"
    source.write_text("int global_var = 1;\n\nvoid f() {}\n", encoding="utf-8")

    assert enclosing_function(source, 1) is None  # global declaration line


def test_enclosing_function_nested_picks_innermost(tmp_path: Path) -> None:
    source = tmp_path / "c.cpp"
    source.write_text(
        "void outer() {\n"
        "    auto inner = []() { return 1; };\n"
        "    inner();\n"
        "}\n",
        encoding="utf-8",
    )

    fn = enclosing_function(source, 3)

    assert fn is not None
    assert fn.name == "outer"
