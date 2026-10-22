"""Deterministic confidence (the LLM never produces it).

conf = round(100 * (0.45*C + 0.35*A + 0.20*(1-R)))
C: share of ALL proposed claims (incl. blocked) with >=1 supporting row that passed the Claim Gate.
A: share of views with relevant rows whose direction agrees with the top cause; A=0 and cap 50 if none.
R: refuting / (supporting + refuting) edges for the top cause.
Partial/unresolved runs are capped at 40.
Weights are a design choice, to be tuned on dev questions only and frozen before the test run.
"""
from __future__ import annotations
W_C, W_A, W_R = 0.45, 0.35, 0.20


def confidence(n_claims: int, n_passed: int, views_agree: int, views_relevant: int,
               support_edges: int, refute_edges: int, partial: bool = False) -> dict:
    C = n_passed / n_claims if n_claims else 0.0
    A = views_agree / views_relevant if views_relevant else 0.0
    R = refute_edges / (support_edges + refute_edges) if (support_edges + refute_edges) else 0.0
    conf = round(100 * (W_C * C + W_A * A + W_R * (1 - R)))
    caps = []
    if not views_relevant:
        conf = min(conf, 50); caps.append("no_relevant_views<=50")
    if partial:
        conf = min(conf, 40); caps.append("partial<=40")
    return {"confidence": conf, "C": round(C, 3), "A": round(A, 3), "R": round(R, 3), "caps": caps,
            "formula": "round(100*(0.45*C + 0.35*A + 0.20*(1-R)))"}
