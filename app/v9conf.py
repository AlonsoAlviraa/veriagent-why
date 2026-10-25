"""V9_full confidence for the V7 answer system (frozen; the answer itself is never changed).

The model is the exact V9_full logistic fitted once on the 600 V9 design rows (bench/export_v9_full.py ->
app/v9_full_model.json; reproduces the documented oodsec hold-out AUROC 0.816 and CRC lambda 0.683).
Decision: answer if p >= crc.lambda (conformal risk control, alpha 0.10 on design rows), else abstain.
Flag: V9_CONFIDENCE=on (default) | off. Off -> {"enabled": false}; callers keep the V7 answer without a score.
Every scored answer is appended to logs/receipts-<run_id>.jsonl as kind=v9_confidence.
"""
from __future__ import annotations
import json, math
from functools import lru_cache
from pathlib import Path
from .config import env

MODEL_PATH = Path(__file__).with_name("v9_full_model.json")


def enabled() -> bool:
    return env("V9_CONFIDENCE", "on").lower() not in ("off", "0", "false")


@lru_cache(maxsize=1)
def model() -> dict:
    return json.loads(MODEL_PATH.read_text())


def vector(o: dict) -> list[float]:
    """Feature vector in model order from a V7+V9 output ({v9: {features, v8_features}}), as bench.v9_final.feats."""
    from bench.abstention import signal as lex  # frozen lexical signal (same function as the benchmark)
    v, v8 = o["v9"]["features"], o["v9"].get("v8_features") or {}
    out = []
    for name in model()["features"]:
        if name == "lex":
            out.append(float(lex(o)))
        elif name.startswith("v8:"):
            out.append(float(v8.get(name[3:]) or 0))
        else:
            out.append(float(v[name]) if v.get(name) is not None else 0.0)
    return out


def prob(x: list[float]) -> float:
    m = model()
    z = m["w"][0] + sum(w * (a - mu) / sd for w, a, mu, sd in zip(m["w"][1:], x, m["mu"], m["sd"]))
    return 1 / (1 + math.exp(-z))


def assess(o: dict, run_id: str | None = None, item_id: str | None = None) -> dict:
    if not enabled():
        return {"enabled": False}
    p = prob(vector(o))
    lam = model()["crc"]["lambda"]
    r = {"enabled": True, "model": "V9_full", "p_correct": round(p, 4), "crc_lambda": round(lam, 4), "alpha": model()["crc"]["alpha"],
         "decision": "answer" if p >= lam else "abstain", "answer": o.get("answer"), "scale": o.get("scale")}
    if run_id:
        from . import nightshift as NS
        prev = dict(NS._RUN)
        NS.set_run(run_id)
        try:
            NS.write_receipt({"kind": "v9_confidence", "item_id": item_id, **{k: r[k] for k in ("p_correct", "crc_lambda", "decision")}})
        finally:
            NS._RUN.update(prev)
    return r


def row_decision(o: dict) -> dict:
    """Abstention decision stored on every benchmark answer row (TRACE_AUDIT P1-3/P2-6).
    Signal = the frozen V9_full p_correct vs the frozen CRC lambda; the model's verbal `confidence` is never used.
    An empty answer is always 'abstain'. Rows without V9 features get decision=None with the reason (no fallback signal)."""
    o = o or {}
    a = o.get("answer")
    items = a if isinstance(a, (list, tuple)) else [a]
    empty = not any(x is not None and str(x).strip() for x in items)
    base = {"signal": "V9_full_frozen", "verbal_confidence_used": False, "gate_passed": o.get("gate_passed")}
    if empty:
        return {**base, "decision": "abstain", "reason": "empty answer", "p_correct": None}
    if not isinstance(o.get("v9"), dict) or "features" not in o["v9"]:
        return {**base, "decision": None, "reason": "no frozen V9 features on this system", "p_correct": None}
    if not enabled():
        return {**base, "decision": None, "reason": "V9_CONFIDENCE=off", "p_correct": None}
    p, lam = prob(vector(o)), model()["crc"]["lambda"]
    return {**base, "decision": "answer" if p >= lam else "abstain", "reason": "p_correct >= crc_lambda" if p >= lam else "p_correct < crc_lambda",
            "p_correct": round(p, 4), "crc_lambda": round(lam, 4)}
