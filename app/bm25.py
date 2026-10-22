"""Minimal BM25 over short texts (ticket text)."""
from __future__ import annotations
import math, re

def tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def bm25(docs: list[str], query: str, k1: float = 1.5, b: float = 0.75) -> list[float]:
    toks = [tok(d) for d in docs]
    n = len(toks) or 1
    avg = sum(map(len, toks)) / n or 1
    df: dict[str, int] = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    scores = []
    for t in toks:
        s = 0.0
        for q in set(tok(query)):
            f = t.count(q)
            if f:
                idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
                s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(t) / avg))
        scores.append(s)
    return scores
