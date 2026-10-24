"""V7 pre-registered abstention (frozen; chosen by bench/abstention_fit.py on TAT-QA train+dev only).

Signal `lex` = confidence_det + confidence_raw / 100 (deterministic gate/trace confidence first,
model self-reported confidence as tie-break; missing -> 0). The agent answers iff lex >= THRESHOLD,
i.e. confidence_det >= 0.8 AND confidence_raw >= 0.9; otherwise it says "I don't know".
Do not edit after the PREREG freeze. See bench/calib/abstention_v7.json for the fit."""
from __future__ import annotations

SIGNAL = "lex"
THRESHOLD = 0.809


def signal(output: dict) -> float:
    raw, det = output.get("confidence"), output.get("confidence_det")
    raw = float(raw) if isinstance(raw, (int, float)) else 0.0
    det = float(det) if isinstance(det, (int, float)) else 0.0
    return det + raw / 100


def answers(output: dict) -> bool:
    return signal(output) >= THRESHOLD - 1e-9


def selective(rows: list[dict], em) -> dict:
    """Coverage / selective EM at the pre-registered point, plus the full risk-coverage curve."""
    ok = [r for r in rows if not r.get("error")]
    ans = [r for r in ok if answers(r["output"])]
    pts = sorted(((signal(r["output"]), em(r)) for r in ok), key=lambda x: (-x[0], x[1]))
    curve, err = [], 0
    for k, (_, c) in enumerate(pts, 1):
        err += 1 - c
        curve.append([round(k / len(pts), 4), round(err / k, 4)])
    return {"signal": SIGNAL, "threshold": THRESHOLD, "n": len(ok), "answered": len(ans),
            "coverage": round(len(ans) / len(ok), 4) if ok else None,
            "selective_em": round(sum(em(r) for r in ans) / len(ans), 4) if ans else None,
            "aurc": round(sum(r for _, r in curve) / len(curve), 4) if curve else None, "risk_coverage_curve": curve}
