"""Shared helpers: deterministic numeric traceability check, BM25 re-use, Wilson CI, SQL guard."""
from __future__ import annotations
import math, re

NUM = re.compile(r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?%?")


def nums(text: str) -> list[float]:
    out = []
    for m in NUM.findall(text or ""):
        s = m.replace("$", "").replace(",", "").rstrip("%")
        try:
            out.append(float(s))
        except ValueError:
            pass
    return out


def supported(value: float, allowed: list[float], free_small_ints: bool = True) -> bool:
    """A number is supported if it matches an allowed number, its x100 (percent) or /100 form,
    within rounding (1% relative or 0.051 absolute). Integers 0..10 are free (list ordinals,
    'top 3') when free_small_ints."""
    if free_small_ints and value == int(value) and 0 <= value <= 10:
        return True
    for a in allowed:
        for b in (a, a * 100, a / 100):
            if abs(value - b) <= max(0.051, 0.01 * abs(b)):
                return True
    return False


def gate_text(text: str, sources: list[str]) -> list[float]:
    """Deterministic traceability check: returns the numbers in `text` not traceable to `sources`."""
    allowed = [x for s in sources for x in nums(s)]
    return [v for v in nums(text) if not supported(v, allowed)]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


_BAD = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|copy|pragma|install|load|export|call|set)\b", re.I)


def safe_sql(sql: str) -> str:
    s = (sql or "").strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", s) or ";" in s or _BAD.search(s):
        raise ValueError("only single read-only SELECT/WITH statements are allowed")
    return s


def derived_pool(allowed: list[float], cap: int = 25) -> list[float]:
    """Numbers recomputable from cited results: for every pair of the first `cap` distinct values,
    a+b, |a-b|, a/b, |a-b|/b (ratios; x100 percent forms are matched in derived_ok) and the mean of two."""
    c = list(dict.fromkeys(abs(x) for x in allowed))[:cap]  # order of appearance (headline rows first)
    out = []
    for i, x in enumerate(c):
        for y in c[i + 1:]:
            out += [x + y, abs(y - x), (x + y) / 2]
            if x:
                out += [y / x, abs(y - x) / x]
            if y:
                out += [x / y, abs(x - y) / y]
    return out


def _decimals(v: float) -> int:
    s = repr(float(v))
    return 0 if s.endswith(".0") else len(s.split(".")[1]) if "." in s else 0


def derived_ok(value: float, pool: list[float]) -> bool:
    """Precision-aware match for recomputed numbers: the claim's value equals a pool number (or its x100
    percent form) rounded to the claim's own decimals (half a unit of its last digit), so a dense pool
    cannot excuse arbitrary numbers."""
    v = abs(value)
    tol = 0.5 * 10 ** (-min(_decimals(v), 4)) + 1e-9
    return any(abs(v - b) <= tol for a in pool for b in (a, a * 100))


def gate_claim(text: str, sources: list[str], derived: bool = True) -> tuple[list[float], list[dict]]:
    """Traceability check with derived numbers. Returns (unsupported numbers, per-number log with reason)."""
    allowed = [x for s in sources for x in nums(s)]
    pool = derived_pool(allowed) if derived else None
    bad, log = [], []
    for v in nums(text):
        if supported(v, allowed):
            log.append({"value": v, "status": "direct"})
        elif derived and derived_ok(v, pool):
            log.append({"value": v, "status": "derived"})
        else:
            bad.append(v)
            log.append({"value": v, "status": "unsupported", "reason": "not in cited results nor recomputable (+,-,/,%change,mean of two)"})
    return bad, log


def bootstrap_mean(xs: list[float], n: int = 2000, seed: int = 2026) -> tuple[float, float]:
    import random
    if not xs:
        return (0.0, 0.0)
    r = random.Random(seed)
    k = len(xs)
    ms = sorted(sum(xs[r.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return (round(ms[int(0.025 * n)], 3), round(ms[int(0.975 * n) - 1], 3))


def brier(conf: list[float], correct: list[int]) -> float:
    return round(sum((c - y) ** 2 for c, y in zip(conf, correct)) / max(1, len(conf)), 4)


def ece(conf: list[float], correct: list[int], bins: int = 10) -> float:
    """Expected calibration error, equal-width bins over [0,1]."""
    n, tot = len(conf), 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(conf) if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        if idx:
            tot += len(idx) / n * abs(sum(conf[i] for i in idx) / len(idx) - sum(correct[i] for i in idx) / len(idx))
    return round(tot, 4) if n else 0.0


def conf01(x) -> float | None:
    """Model-reported confidence (0-1 or 0-100) -> [0,1]; None if absent/unparseable."""
    try:
        v = float(str(x).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    v = v / 100 if v > 1 else v
    return min(1.0, max(0.0, v))

