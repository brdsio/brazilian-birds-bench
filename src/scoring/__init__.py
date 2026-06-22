"""Scoring helpers for the brazilian-birds-bench benchmark.

This package holds the *normalization* and metric logic used at evaluation
time. It is deliberately separate from the dataset pipeline (``parsing`` /
``enrichment``): the dataset preserves the official, canonical names, while the
scorer normalizes copies of those strings only for comparison -- never mutating
what is stored on disk.
"""

from __future__ import annotations

from .normalize import normalize_for_match

__all__ = ["normalize_for_match"]
