from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at_k(gold_files: Sequence[str], ranked_files: Sequence[str], k: int) -> float:
    """Share of the fix's files surfaced in the top k. Punishes fixes we only partly locate."""

    if not gold_files:
        return 0.0
    return len(set(gold_files) & set(ranked_files[:k])) / len(set(gold_files))


def hit_at_k(gold_files: Sequence[str], ranked_files: Sequence[str], k: int) -> float:
    """Did the top k contain *any* correct file? The "gave the human a real lead" metric."""

    return float(bool(set(gold_files) & set(ranked_files[:k])))


def reciprocal_rank(gold_files: Sequence[str], ranked_files: Sequence[str]) -> float:
    """How far down the first correct file sits. Separates "ranked 1st" from "ranked 9th"."""

    gold = set(gold_files)
    for index, path in enumerate(ranked_files, start=1):
        if path in gold:
            return 1.0 / index
    return 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile; for an interactive tool the tail matters more than the mean."""

    if not values:
        return 0.0
    ordered = sorted(values)
    # ceil, not round: round() uses banker's rounding, so p50 of two samples would pick the
    # larger one while p50 of four picked the smaller — the metric has to be consistent.
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]
