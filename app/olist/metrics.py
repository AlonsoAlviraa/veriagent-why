"""Olist metric registry: each claim's value is defined by exactly one SQL statement built here, used
both when the memo is written and when POST /verify re-executes it.

Claim: {id, metric: "olist.<name>", params: {...}, value, row_ids: [order_id, ...]}
  value    re-computed now; rates (pp) tolerance +/-0.5, days/per-day tolerance +/-1%
  row_ids  cited orders; each must still exist, fall inside the claim's filter and satisfy the
           metric's "witness" predicate (e.g. still late), otherwise the receipt is red.
SQL uses only plain ANSI constructs that both DuckDB and Zetaris Lightning (Spark SQL) run.
"""
from __future__ import annotations
import datetime as dt

TABLES = ("ol_orders", "ol_items", "ol_reviews", "ol_sellers")
RATE_TOL_PP, REL_TOL = 0.5, 0.01

# Order-level groups for review metrics (uncorrelated IN-subqueries; order_id is never NULL).
GROUPS = {
    "late": "o.late",
    "freight_heavy": "o.order_id IN (SELECT order_id FROM ol_items GROUP BY order_id HAVING SUM(freight) >= 0.3 * SUM(price))",
    "interstate": ("o.order_id IN (SELECT i.order_id FROM ol_items i JOIN ol_sellers s ON i.seller_id = s.seller_id "
                   "JOIN ol_orders o2 ON o2.order_id = i.order_id WHERE s.seller_state <> o2.customer_state)"),
    "multi_seller": "o.order_id IN (SELECT order_id FROM ol_items GROUP BY order_id HAVING COUNT(DISTINCT seller_id) > 1)",
}
SOURCES_OF_GROUP = {"late": ["ol_orders"], "freight_heavy": ["ol_items"], "interstate": ["ol_items", "ol_sellers"],
                    "multi_seller": ["ol_items"]}


def _days(w):
    a, b = (dt.date.fromisoformat(x) for x in w)
    return (b - a).days + 1


def spec(metric: str, p: dict) -> dict:
    """-> {from, where, params, value, witness, kind, sources}."""
    name = metric.removeprefix("olist.")
    where, params = ["o.delivered", "o.purchase_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)"], list(p["window"])
    if p.get("state"):
        where.append("o.customer_state = ?"); params.append(p["state"])
    if p.get("not_state"):
        where.append("o.customer_state <> ?"); params.append(p["not_state"])
    src = ["ol_orders"]
    frm = "ol_orders o"
    if name == "late_rate":
        val, wit, kind = "AVG(CASE WHEN o.late THEN 100.0 ELSE 0.0 END)", "o.late", "rate"
    elif name in ("avg_handling_days", "avg_transit_days", "avg_delivery_days"):
        col = "o." + name.removeprefix("avg_")
        where.append(f"{col} IS NOT NULL")
        val, wit, kind = f"AVG({col})", "TRUE", "rel"
    elif name == "orders_per_day":
        val, wit, kind = f"COUNT(*) / {float(_days(p['window']))}", "TRUE", "rel"
    elif name == "low_review_rate":
        frm = "ol_orders o JOIN ol_reviews r ON r.order_id = o.order_id"
        src.append("ol_reviews")
        g = p.get("group")
        if g:
            if g not in GROUPS:
                raise ValueError(f"unknown group {g}")
            where.append(GROUPS[g] if p.get("in_group", True) else f"NOT ({GROUPS[g]})")
            src += [s for s in SOURCES_OF_GROUP[g] if s not in src]
        val, wit, kind = "AVG(CASE WHEN r.score <= 2 THEN 100.0 ELSE 0.0 END)", "r.score <= 2", "rate"
    else:
        raise ValueError(f"unsupported olist metric {metric}")
    return {"from": frm, "where": " AND ".join(where), "params": params, "value": val, "witness": wit,
            "kind": kind, "sources": src}


def metric_sql(metric: str, p: dict) -> tuple[str, list]:
    s = spec(metric, p)
    return f"SELECT {s['value']} AS v FROM {s['from']} WHERE {s['where']}", s["params"]


def value(db, metric: str, p: dict) -> float | None:
    sql, params = metric_sql(metric, p)
    r = db.query(sql, params)
    v = r[0]["v"] if r else None
    return None if v is None else float(v)


def witnesses(db, metric: str, p: dict, k: int = 3) -> list[str]:
    """First k order ids (sorted, deterministic) that satisfy the filter and the witness predicate."""
    s = spec(metric, p)
    r = db.query(f"SELECT DISTINCT o.order_id AS id FROM {s['from']} WHERE {s['where']} AND {s['witness']} "
                 f"ORDER BY id LIMIT {int(k)}", s["params"])
    return [x["id"] for x in r]


def check(db, claim: dict) -> dict:
    s = spec(claim["metric"], claim["params"])
    reasons, ids = [], claim.get("row_ids") or []
    if not ids:
        reasons.append("no cited rows")
    else:
        ph = ",".join("?" * len(ids))
        r = db.query(f"SELECT DISTINCT o.order_id AS id FROM {s['from']} WHERE {s['where']} AND {s['witness']} "
                     f"AND o.order_id IN ({ph})", [*s["params"], *ids])
        ok = {x["id"] for x in r}
        bad = [i for i in ids if i not in ok]
        if bad:
            reasons.append(f"cited rows missing or no longer matching: {bad}")
    actual = value(db, claim["metric"], claim["params"])
    if actual is None:
        reasons.append("no data for metric")
    else:
        tol = RATE_TOL_PP if s["kind"] == "rate" else abs(actual) * REL_TOL
        if abs(actual - float(claim["value"])) > tol:
            reasons.append(f"value {claim['value']} != db {round(actual, 3)}")
    return {"claim_id": claim["id"], "passed": not reasons, "reasons": reasons, "db_value": actual}
