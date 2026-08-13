from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from pathlib import PurePosixPath

from repopilot.models import RankedFile
from repopilot.tools.search_tools import SearchResult

# Directory names that conventionally hold copies of other projects. A bug in vendored code is
# fixed upstream, not here, so these are rarely the answer. Deliberately a general convention
# list rather than names tuned to one repository — tuning it on the eval set would be cheating.
VENDORED_DIRECTORIES = frozenset(
    {
        "3rdparty", "3rd_party", "third_party", "thirdparty",
        "external", "extern", "vendor", "vendored", "bundled",
        "deps", "dependencies", "node_modules",
    }
)

DEFAULT_VENDORED_PENALTY = 0.1

# BM25-style length-normalisation parameter: 0 disables, 0.75 is the standard BM25 value.
LENGTH_NORM_B = 0.75


def is_vendored(path: str) -> bool:
    return any(part.lower() in VENDORED_DIRECTORIES for part in PurePosixPath(path).parts)


def inverse_document_frequency(document_frequency: int, corpus_files: int) -> float:
    """Rare terms carry the signal: `icvCvt_BGRA2RGBA_16u_C4R` means far more than `width`.

    Smoothed so a term appearing in every file still scores slightly above zero rather than
    going negative, which would actively reward files for *not* matching the query.
    """

    if corpus_files <= 0:
        return 1.0
    return math.log(1 + corpus_files / (1 + document_frequency))


def term_weight(
    hit_count: int, doc_lines: int = 0, avg_lines: float = 0.0,
    b: float = LENGTH_NORM_B,
) -> float:
    """Sublinear term frequency with BM25-style length normalisation.

    500 occurrences is more relevant than 1, but nowhere near 500 times more; and a
    22k-line vendored header matching a common word means less than a 700-line source
    file matching the same word, because the big file matches almost everything.
    """

    tf = 1.0 + math.log(hit_count) if hit_count > 0 else 0.0
    if doc_lines > 0 and avg_lines > 0:
        tf = tf / (1.0 - b + b * (doc_lines / avg_lines))
    return tf


def rank_files(
    results: Sequence[SearchResult],
    *,
    use_idf: bool = True,
    vendored_penalty: float = DEFAULT_VENDORED_PENALTY,
    # Off by default: BM25 length normalisation assumes length ~ redundancy, which is
    # wrong for source trees where the big files ARE the implementation. Measured on the
    # OpenCV eval set it crashed Hit@10 0.750 -> 0.283 by demoting exactly those files.
    use_length_norm: bool = False,
) -> list[RankedFile]:
    """The single definition of "which files answer the question", shared by the planner and eval.

    Scores every file that matched any keyword — not only the files that survived evidence
    truncation — so a correct file can no longer be lost purely because a common keyword filled
    the citation budget first.
    """

    corpus_files = max((result.corpus_files for result in results), default=0)
    corpus_total_lines = max((result.corpus_total_lines for result in results), default=0)
    avg_lines = corpus_total_lines / corpus_files if corpus_files > 0 else 0.0

    scores: dict[str, float] = defaultdict(float)
    keywords: dict[str, set[str]] = defaultdict(set)
    hit_counts: dict[str, int] = defaultdict(int)
    for result in results:
        weight = (
            inverse_document_frequency(len(result.matches), corpus_files) if use_idf else 1.0
        )
        for match in result.matches:
            tf = term_weight(
                len(match.hit_lines),
                match.total_lines if use_length_norm else 0,
                avg_lines if use_length_norm else 0.0,
            )
            scores[match.path] += weight * tf
            keywords[match.path].add(result.keyword)
            hit_counts[match.path] += len(match.hit_lines)

    evidence_ids: dict[str, list[str]] = defaultdict(list)
    for result in results:
        for item in result.evidence:
            evidence_ids[item.path].append(item.id)

    ranked = [
        RankedFile(
            path=path,
            score=score * (vendored_penalty if is_vendored(path) else 1.0),
            keyword_count=len(keywords[path]),
            evidence_count=hit_counts[path],
            evidence_ids=evidence_ids[path],
        )
        for path, score in scores.items()
    ]
    # Path breaks ties so equal-scoring files stay in a reproducible order across machines.
    ranked.sort(key=lambda file: (-file.score, file.path))
    return ranked
