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


def test_classify_lines_definition_vs_use(tmp_path: Path) -> None:
    from repopilot.symbols import classify_lines

    source = tmp_path / "d.cpp"
    source.write_text(
        "int add(int a, int b) {\n"   # line 1: signature -> definition
        "    return a + b;\n"         # line 2: body -> use
        "}\n"
        "void caller() {\n"           # line 4: signature -> definition
        "    add(1, 2);\n"            # line 5: body -> use
        "}\n",
        encoding="utf-8",
    )

    kinds = classify_lines(source, [1, 2, 4, 5, 99])

    assert kinds[1] == "definition"
    assert kinds[2] == "use"
    assert kinds[4] == "definition"
    assert kinds[5] == "use"
    assert kinds[99] is None
