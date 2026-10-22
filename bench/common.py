"""Shared helpers: deterministic numeric claim gate, BM25 re-use, Wilson CI, SQL guard."""
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
    """Deterministic claim gate: returns the numbers in `text` not traceable to `sources`."""
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
