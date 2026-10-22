"""KPI registry. Agents are written against a 'good outcome' table shaped like v_logistics
(shipment_id, order_id, carrier, region, ship_date, on_time). A KPI lens rewrites v_logistics into
a derived table for the chosen KPI, so the same SQL, checks and Claim Gate apply to every KPI.
  on_time_rate: good = delivered on time (date = ship date)
  return_rate:  good = order not returned (date = order date); reported as the return rate"""
from __future__ import annotations
import re

KPIS = {
    "on_time_rate": {"label": "On-time rate", "bad": "late shipments", "invert": False, "table": None,
                     "patterns": [r"on[- ]time", r"late deliver", r"delivery delay"]},
    "return_rate": {"label": "Return rate", "bad": "returned orders", "invert": True,
                    "patterns": [r"return rate", r"returns? (went|rose|increase)", r"\breturns\b"],
                    "table": "(SELECT l.shipment_id, l.order_id, l.carrier, l.region, o.order_date AS ship_date, "
                             "l.promised_days, l.actual_days, (rr.order_id IS NULL) AS on_time FROM v_logistics l "
                             "JOIN v_orders o USING(order_id) LEFT JOIN (SELECT DISTINCT order_id FROM v_returns) rr USING(order_id))"},
}


def detect(query: str) -> str | None:
    for k, v in KPIS.items():
        if any(re.search(p, query, re.I) for p in v["patterns"]):
            return k
    return None


class KpiLens:
    def __init__(self, db, kpi: str):
        self.db, self.kpi = db, KPIS[kpi]
        self.name = f"{db.name} [{kpi}]"

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        t = self.kpi["table"]
        if t:
            sql = re.sub(r"\bv_logistics(\s+l\b)?", lambda m: f"{t} l" if m.group(1) else f"{t} v_kpi", sql)
        return self.db.query(sql, params)


def display_rate(kpi: str, good_rate_pct: float) -> float:
    return round(100 - good_rate_pct, 2) if KPIS[kpi]["invert"] else round(good_rate_pct, 2)
