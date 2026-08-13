from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from repopilot.eval.dataset import EvalCase, load_dataset, save_dataset
from repopilot.eval.metrics import hit_at_k, percentile, recall_at_k, reciprocal_rank
from repopilot.eval.runner import CaseResult, aggregate
from repopilot.ranking import rank_files, term_weight
from repopilot.tools.search_tools import FileMatches, SearchResult

GOLD = ["src/a.cpp", "src/b.cpp"]


def make_case(**overrides: object) -> EvalCase:
    defaults = dict(
        case_id="repo-1",
        repo="o/r",
        issue_number=1,
        issue_url="https://example.invalid/1",
        title="Crash in resize",
        body="stack trace and reproduction steps",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        pr_number=2,
        base_sha="a" * 40,
        gold_files=GOLD,
        changed_files_total=2,
        body_mentions_gold_path=False,
    )
    return EvalCase(**{**defaults, **overrides})


def make_result(ranked: list[str], **overrides: object) -> CaseResult:
    defaults = dict(
        case_id="repo-1",
        gold_files=GOLD,
        ranked_files=ranked,
        keywords=["resize"],
        strategy="deterministic",
        evidence_count=len(ranked),
        latency_ms=100.0,
        body_mentions_gold_path=False,
        error=None,
    )
    return CaseResult(**{**defaults, **overrides})


def test_recall_counts_share_of_gold_files_found() -> None:
    assert recall_at_k(GOLD, ["src/a.cpp", "x", "y"], 3) == 0.5
    assert recall_at_k(GOLD, ["src/a.cpp", "src/b.cpp"], 3) == 1.0
    assert recall_at_k(GOLD, ["x", "src/a.cpp"], 1) == 0.0


def test_hit_is_binary_while_recall_is_partial() -> None:
    """The two metrics must disagree here; that disagreement is the reason both are reported."""
    assert hit_at_k(GOLD, ["src/a.cpp", "x"], 2) == 1.0
    assert recall_at_k(GOLD, ["src/a.cpp", "x"], 2) == 0.5


def test_reciprocal_rank_uses_first_correct_position() -> None:
    assert reciprocal_rank(GOLD, ["x", "y", "src/b.cpp"]) == 1 / 3
    assert reciprocal_rank(GOLD, ["src/a.cpp"]) == 1.0
    assert reciprocal_rank(GOLD, ["x", "y"]) == 0.0


def test_percentile_is_nearest_rank_and_stable_for_small_samples() -> None:
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert percentile([1, 2, 3, 4, 5], 0.95) == 5
    assert percentile([10, 20], 0.5) == 10
    assert percentile([], 0.5) == 0.0


def search_result(keyword: str, hits: dict[str, int], corpus_files: int = 1_000) -> SearchResult:
    return SearchResult(
        keyword=keyword,
        corpus_files=corpus_files,
        matches=[
            FileMatches(path=path, hit_lines=list(range(1, count + 1)))
            for path, count in hits.items()
        ],
        evidence=[],
    )


def test_idf_lets_one_rare_symbol_beat_many_common_word_hits() -> None:
    """The baseline's top failure: a huge changelog full of common English words outranking
    the source file that contains the one symbol the issue actually named."""
    common = search_result("width", {"docs/CHANGELOG": 50, **{f"f{i}.c": 1 for i in range(899)}})
    rare = search_result("icvCvt_BGRA2RGBA", {"src/utils.cpp": 1})

    with_idf = [file.path for file in rank_files([common, rare])]
    without_idf = [file.path for file in rank_files([common, rare], use_idf=False)]

    assert with_idf[0] == "src/utils.cpp"
    assert without_idf[0] == "docs/CHANGELOG"


def test_vendored_directories_are_demoted() -> None:
    result = search_result("parse", {"3rdparty/libtiff/tif.c": 10, "modules/core/parse.cpp": 10})

    demoted = [file.path for file in rank_files([result])]
    disabled = [file.path for file in rank_files([result], vendored_penalty=1.0)]

    assert demoted[0] == "modules/core/parse.cpp"
    assert disabled[0] == "3rdparty/libtiff/tif.c"  # tie broken by path when the prior is off


def test_term_weight_is_sublinear() -> None:
    """500 hits is more relevant than 1, but nowhere near 500 times more."""
    assert term_weight(1) == 1.0
    assert 1.0 < term_weight(500) < 10.0


def test_ranking_covers_files_that_never_reached_the_evidence_budget() -> None:
    """Scoring the full match pool is what stops a correct file being lost to truncation."""
    result = search_result("resize", {"src/resize.cpp": 3})

    ranked = rank_files([result])

    assert [file.path for file in ranked] == ["src/resize.cpp"]
    assert ranked[0].evidence_ids == []


def test_aggregate_excludes_errors_from_scores_but_reports_them() -> None:
    results = [
        make_result(["src/a.cpp", "src/b.cpp"]),
        make_result([], error="RuntimeError: boom"),
    ]

    metrics = aggregate(results, k_values=(1,))

    assert metrics["cases"] == 2
    assert metrics["errors"] == 1
    assert metrics["recall@1"] == 0.5  # scored over the one successful case only


def test_aggregate_reports_leak_free_subset_separately() -> None:
    """Cases whose text names a gold file inflate scores, so the honest subset is reported too."""
    results = [
        make_result(["src/a.cpp", "src/b.cpp"], body_mentions_gold_path=True),
        make_result(["nope.cpp"], body_mentions_gold_path=False),
    ]

    metrics = aggregate(results, k_values=(5,))

    assert metrics["recall@5"] == 0.5
    assert metrics["clean_cases"] == 1
    assert metrics["clean_recall@5"] == 0.0


def test_question_budget_controls_how_much_body_reaches_the_retriever() -> None:
    case = make_case(title="Crash", body="x" * 5_000)

    assert case.question(body_chars=0) == "Crash"
    assert len(case.question(body_chars=100)) == len("Crash\n\n") + 100


def test_dataset_round_trips_through_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    save_dataset([make_case(), make_case(case_id="repo-2")], path)

    loaded = load_dataset(path)

    assert [case.case_id for case in loaded] == ["repo-1", "repo-2"]
    assert loaded[0].gold_files == GOLD
