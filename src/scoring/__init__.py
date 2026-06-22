"""Scoring helpers for the brazilian-birds-bench benchmark.

This package holds the *normalization* and metric logic used at evaluation
time. It is deliberately separate from the dataset pipeline (``parsing`` /
``enrichment``): the dataset preserves the official, canonical names, while the
scorer normalizes copies of those strings only for comparison -- never mutating
what is stored on disk.
"""

from __future__ import annotations

from .normalize import normalize_for_match
from .scorer import score_results, score_row
from .taxonomy import build_name_index, classify_error, taxonomic_distance

__all__ = [
    "build_name_index",
    "classify_error",
    "normalize_for_match",
    "score_results",
    "score_row",
    "taxonomic_distance",
]
