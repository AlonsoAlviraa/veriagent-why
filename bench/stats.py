"""Paired significance for comparison tables (trace-fix 9): paired bootstrap CI of the mean difference and an
exact two-sided McNemar test for binary outcomes. Pure stdlib, deterministic (seeded)."""
from __future__ import annotations
import math, random


def paired_bootstrap(a: list[float], b: list[float], n: int = 10000, seed: int = 0) -> dict:
    """Mean(b - a) over paired items with a 95% percentile CI and a two-sided bootstrap p-value."""
    assert len(a) == len(b) and a, "paired lists of equal non-zero length required"
    d = [y - x for x, y in zip(a, b)]
    k = len(d)
    rng = random.Random(seed)
    means = sorted(sum(d[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    obs = sum(d) / k
    lo, hi = means[int(0.025 * n)], means[int(0.975 * n) - 1]
    p = 2 * min(sum(m <= 0 for m in means) / n, sum(m >= 0 for m in means) / n)
    return {"n": k, "mean_diff": round(obs, 4), "ci95": [round(lo, 4), round(hi, 4)], "p": round(min(1.0, p), 4)}


def mcnemar(a: list[bool], b: list[bool]) -> dict:
    """Exact binomial McNemar on discordant pairs: b01 = a wrong & b right, b10 = a right & b wrong."""
    assert len(a) == len(b)
    b01 = sum((not x) and y for x, y in zip(a, b))
    b10 = sum(x and (not y) for x, y in zip(a, b))
    m = b01 + b10
    if m == 0:
        return {"b01": 0, "b10": 0, "p": 1.0}
    tail = sum(math.comb(m, i) for i in range(0, min(b01, b10) + 1)) / 2 ** m
    return {"b01": b01, "b10": b10, "p": round(min(1.0, 2 * tail), 4)}
