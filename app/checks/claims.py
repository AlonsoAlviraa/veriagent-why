"""Deterministic claim checker, shared by the Traceability Check and (later) the eval harness.

A claim: {id, metric, segment: {col: val}, window: [start, end], value, row_ids: [...]}.
Checks: cited row IDs exist in v_logistics and match the claim's segment and window; the
value matches the DB within tolerance (rates: +/-0.5 pp; counts/amounts: +/-1%).
"""
from __future__ import annotations

RATE_TOL_PP = 0.5
AMOUNT_TOL = 0.01
SEG_COLS = {"carrier": "l.carrier", "region": "l.region", "category": "o.category"}
FROM = "v_logistics l JOIN v_orders o USING(order_id)"


def metric_sql(metric: str, segment: dict, window: list[str]) -> tuple[str, list]:
    """The exact SQL (and bound params) that defines a claim's value. Used by the Traceability Check and by
    POST /verify, so the receipt re-executes the same statement the claim was built from."""
    where, params = ["l.ship_date BETWEEN ? AND ?"], [window[0], window[1]]
    for c, v in segment.items():
        if c not in SEG_COLS:
            raise ValueError(f"unsupported segment column {c}")
        where.append(f"{SEG_COLS[c]} = ?"); params.append(v)
    w = " AND ".join(where)
    if metric == "on_time_rate":
        return f"SELECT AVG(CASE WHEN l.on_time THEN 100.0 ELSE 0 END) AS v FROM {FROM} WHERE {w}", params
    if metric == "late_count":
        return f"SELECT SUM(CASE WHEN l.on_time THEN 0 ELSE 1 END) AS v FROM {FROM} WHERE {w}", params
    raise ValueError(f"unsupported metric {metric}")


def metric_value(db, metric: str, segment: dict, window: list[str]) -> float | None:
    sql, params = metric_sql(metric, segment, window)
    r = db.query(sql, params)
    v = r[0]["v"] if r else None
    return None if v is None else float(v)


def check_claim(db, claim: dict) -> dict:
    reasons = []
    ids = claim.get("row_ids") or []
    if not ids:
        reasons.append("no cited rows")
    else:
        ph = ",".join("?" * len(ids))
        rows = db.query(f"SELECT l.shipment_id, l.carrier, l.region, o.category, CAST(l.ship_date AS VARCHAR) AS d FROM {FROM} WHERE l.shipment_id IN ({ph})", ids)
        found = {r["shipment_id"]: r for r in rows}
        missing = [i for i in ids if i not in found]
        if missing:
            reasons.append(f"row ids not found: {missing}")
        for r in found.values():
            if any(r[c] != v for c, v in claim["segment"].items()) or not (claim["window"][0] <= r["d"] <= claim["window"][1]):
                reasons.append(f"row {r['shipment_id']} does not match segment/window"); break
    actual = metric_value(db, claim["metric"], claim["segment"], claim["window"])
    if actual is None:
        reasons.append("no data for metric")
    else:
        tol = RATE_TOL_PP if claim["metric"].endswith("_rate") else abs(actual) * AMOUNT_TOL
        if abs(actual - float(claim["value"])) > tol:
            reasons.append(f"value {claim['value']} != db {round(actual, 2)}")
    return {"claim_id": claim["id"], "passed": not reasons, "reasons": reasons, "db_value": actual}


NUM = __import__("re").compile(r"(?<![\w-])\d+(?:\.\d+)?")


def check_narrative(text: str, sources: list[str]) -> dict:
    """Every number in model-written prose must appear in the approved facts (within 0.05)."""
    allowed = [float(x) for s in sources for x in NUM.findall(s)]
    bad = [n for n in NUM.findall(text) if not any(abs(float(n) - a) <= 0.05 for a in allowed)]
    return {"claim_id": "narrative", "passed": not bad, "reasons": [f"unsupported numbers: {bad}"] if bad else []}
