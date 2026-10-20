"""Aggregation and 95% bootstrap confidence intervals.

The unit of resampling is the task: each task's value is the mean over its
runs, and tasks are drawn with replacement. Runs of one task are not
independent (same checker, same start state), so resampling attempts would
make the intervals too narrow.
"""

from __future__ import annotations

import random
from statistics import mean

RESAMPLES = 10_000
SEED = 20261020


def task_means(values_by_task: dict[str, list[float]]) -> list[float]:
    return [mean(v) for v in values_by_task.values() if v]


def bootstrap_ci(values: list[float], resamples: int = RESAMPLES, seed: int = SEED) -> tuple[float, float, float]:
    """(mean, lo, hi) with a percentile 95% interval."""
    if not values:
        return (float("nan"),) * 3
    m = mean(values)
    if len(values) == 1:
        return (m, m, m)
    rng = random.Random(seed)
    n = len(values)
    draws = sorted(mean(values[rng.randrange(n)] for _ in range(n)) for _ in range(resamples))
    lo = draws[int(0.025 * resamples)]
    hi = draws[min(resamples - 1, int(0.975 * resamples))]
    return (m, lo, hi)


def overlap(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return not (a[2] < b[1] or b[2] < a[1])


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
