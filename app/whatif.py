"""What-if (ESTIMATE): recompute the period on-time rate as if the top-cause segment had stayed at
its own baseline late rate. A recalculation over the same rows; model-based, not observed."""
from __future__ import annotations
from .checks.claims import SEG_COLS, FROM


def whatif(db, result: dict) -> dict:
    q, top = result["question"], result["analysis"]["top_cause"]
    if not top or not top["segment"]:
        return {"label": "ESTIMATE", "available": False, "reason": "no single segment to neutralise"}
    w = " AND ".join(f"{SEG_COLS[c]} = ?" for c in top["segment"])
    v = list(top["segment"].values())
    def agg(where, params, win):
        r = db.query(f"SELECT COUNT(*) n, SUM(CASE WHEN NOT l.on_time THEN 1 ELSE 0 END) late FROM {FROM} WHERE {where} AND l.ship_date BETWEEN ? AND ?", [*params, *win])[0]
        return r["n"] or 0, r["late"] or 0
    n_all, late_all = agg("TRUE", [], q["period"])
    n_seg, late_seg = agg(w, v, q["period"])
    nb, lb = agg(w, v, q["baseline"])
    exp_seg = n_seg * (lb / nb) if nb else late_seg
    observed = 100 * (1 - late_all / n_all)
    est = 100 * (1 - (late_all - late_seg + exp_seg) / n_all)
    return {"label": "ESTIMATE", "available": True, "badge": "ESTIMATE - model-based, not observed",
            "neutralised_segment": top["segment"], "observed_on_time_rate": round(observed, 2),
            "estimated_on_time_rate_if_segment_at_baseline": round(est, 2),
            "method": "replace the segment's period late count with its period volume x its own baseline late rate"}
