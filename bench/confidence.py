"""Declared confidence formulas (trace-fix 8). Every system returns conf_formula (an id below) + conf_inputs, and the
audit trace recomputes the value with the SAME function, so the logged formula always matches the logged number
(REPORT.md section 3: 883 traces had a formula string that did not match). Calibration maps are fitted on TAT-QA
TRAIN / the 30 InsightBench TUNE tasks only (scripts/fit_trace_fixes.py -> bench/calib/*.json)."""
from __future__ import annotations
import json, os
from pathlib import Path
from .fixes import isotonic_apply

CAL = Path(__file__).resolve().parent / "calib"
RELEVANCE_MIN = 0.001  # mirrors bench.markov.RELEVANCE_MIN (TRAIN-calibrated)


def load_map(bench: str):
    env = os.environ.get("CR_CONF_MAP_" + bench.upper())
    if env:
        return json.loads(env)
    p = CAL / f"cr_{bench}.json"
    return json.loads(p.read_text())["map"] if p.exists() else None


def tat_det(gate_rounds: int, gate_passed: bool, traceable: bool, rerank_p=None) -> float:
    det = (0.8 if gate_rounds == 1 else 0.55) if gate_passed else 0.2
    if not traceable:
        det = min(det, 0.1)
    if rerank_p is not None and rerank_p < RELEVANCE_MIN:
        det = min(det, 0.4)
    return det


def ib_det(n_q: int, n_unusable: int, n_kept: int, n_dropped: int) -> float:
    if not n_q or not n_kept:
        return 0.1
    return round(min(0.9, 0.2 + 0.7 * (1 - n_unusable / n_q) * (n_kept / (n_kept + n_dropped))), 3)


def vr_score(vr_score: float) -> float:
    return round(vr_score / 100, 3)


def cr_tat(p_correct, gate_passed: bool, revised: bool, cmap=None) -> float:
    if revised:
        return 0.4
    if p_correct is None:
        return 0.2
    c = isotonic_apply(cmap, p_correct) if cmap else p_correct
    return c if gate_passed else min(c, 0.2)


def cr_ib(p_correct, base_det: float, cmap=None) -> float:
    if p_correct is None:
        return base_det
    if cmap:  # isotonic P(judge>=0.6 | p_correct) on the 30 TUNE tasks, capped by evidence quality
        return round(min(isotonic_apply(cmap, p_correct), base_det if base_det <= 0.1 else 1.0), 3)
    return round(min(0.9, base_det * (0.5 + 0.5 * p_correct)), 3)


def fixed(value: float, rule: str = "") -> float:
    """Configs whose confidence is a declared rule over discrete outcomes (pot / sc); the rule text is logged."""
    return value


FORMULAS = {
    "tat_det": (tat_det, "0.8 if gate passed in round 0; 0.55 if passed after a retry; 0.2 if gate failed; capped at 0.1 if answer not traceable; capped at 0.4 if reranker relevance < RELEVANCE_MIN"),
    "ib_det": (ib_det, "0.1 if no results or no kept claims; else min(0.9, 0.2 + 0.7 * share_results_usable(non-error, >=1 row) * share_claims_kept)"),
    "vr_score": (vr_score, "best verify-retry score / 100 (score = 0.5*deterministic + 0.5*verifier)"),
    "cr_tat": (cr_tat, "revised -> 0.4; else isotonic(p_correct) fitted on TAT-QA TRAIN (bench/calib/cr_tatqa.json), capped at 0.2 if gate failed"),
    "cr_ib": (cr_ib, "isotonic P(judge>=0.6 | critic p_correct) fitted on the 30 InsightBench TUNE tasks; 0.1 cap when no usable evidence"),
    "fixed": (fixed, "declared rule over discrete outcomes (see conf_inputs.rule)"),
}


def recompute(formula: str | None, inputs: dict | None):
    if formula not in FORMULAS or inputs is None:
        return None
    return FORMULAS[formula][0](**inputs)
