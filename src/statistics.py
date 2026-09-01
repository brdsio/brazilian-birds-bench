"""Uncertainty estimates and paired comparisons for benchmark result files."""

from __future__ import annotations

import math
import random


def _is_true(value: object) -> bool:
    return value in (True, "True", 1, "1")


def bootstrap_accuracy_ci(
    rows: list[dict[str, object]],
    metric: str = "acceptable_match",
    *,
    samples: int = 10_000,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Return accuracy and a percentile 95% bootstrap CI over species."""
    values = [int(_is_true(row.get(metric))) for row in rows]
    if not values:
        raise ValueError("Cannot estimate accuracy from an empty result set.")
    rng = random.Random(seed)
    n = len(values)
    probability = sum(values) / n
    estimates = sorted(
        rng.binomialvariate(n=n, p=probability) / n
        for _ in range(samples)
    )
    lo = estimates[int(0.025 * samples)]
    hi = estimates[min(samples - 1, int(0.975 * samples))]
    return probability, lo, hi


def mcnemar_exact(
    left: list[dict[str, object]],
    right: list[dict[str, object]],
    metric: str = "acceptable_match",
) -> dict[str, float | int]:
    """Return paired discordances and the two-sided exact McNemar p-value."""
    left_by_id = {str(row["cbro_id"]): _is_true(row.get(metric)) for row in left}
    right_by_id = {str(row["cbro_id"]): _is_true(row.get(metric)) for row in right}
    shared = sorted(left_by_id.keys() & right_by_id.keys())
    left_only = sum(left_by_id[key] and not right_by_id[key] for key in shared)
    right_only = sum(right_by_id[key] and not left_by_id[key] for key in shared)
    discordant = left_only + right_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(
            math.comb(discordant, k) for k in range(min(left_only, right_only) + 1)
        ) / (2**discordant)
        p_value = min(1.0, 2 * tail)
    return {
        "n_paired": len(shared),
        "left_only_correct": left_only,
        "right_only_correct": right_only,
        "discordant": discordant,
        "p_value": p_value,
    }
