"""Plain-RAG baseline: same data, same question, same token budget, same model (in live mode).

Retrieval: every row of the 5 views inside the baseline+period windows is serialised as text
("<view> <col> <val> ...", with row id); BM25 against the question; top rows up to TOKEN_BUDGET
whitespace tokens. No planning, no filtering, no verification loop, no claim gate.
Reader: live mode -> the model picks top_cause_label from the fixed taxonomy citing row ids.
Sample mode (no model) -> a fixed, documented reader rule: if >=50% of the retrieved late
logistics rows share one carrier+region -> carrier_sla_breach; elif a promotion row was
retrieved -> promotion_effect; else none.
"""
from __future__ import annotations
import json
from collections import Counter
from app.adapters.zetaris import SampleBackend
from app.bm25 import bm25
from app.config import provider
from app.agents.llm_steps import TAXONOMY, _json
from app import llm

TOKEN_BUDGET = 600  # default; eval.py passes the agent's own S2 context size per question (matched budget)


def rows_as_text(db, q):
    b0, p1 = q["baseline"][0], q["period"][1]
    out = []
    for r in db.query("SELECT shipment_id, carrier, region, CAST(ship_date AS VARCHAR) d, on_time FROM v_logistics WHERE ship_date BETWEEN ? AND ?", [b0, p1]):
        out.append((r["shipment_id"], f"v_logistics {r['shipment_id']} carrier {r['carrier']} region {r['region']} date {r['d']} on time {r['on_time']} {'late delivery' if not r['on_time'] else ''}", r))
    for r in db.query("SELECT t.ticket_id, t.text, CAST(t.created_date AS VARCHAR) d FROM v_tickets t WHERE created_date BETWEEN ? AND ?", [b0, p1]):
        out.append((r["ticket_id"], f"v_tickets {r['ticket_id']} {r['d']} {r['text']}", None))
    for r in db.query("SELECT return_id, reason, CAST(return_date AS VARCHAR) d FROM v_returns WHERE return_date BETWEEN ? AND ?", [b0, p1]):
        out.append((r["return_id"], f"v_returns {r['return_id']} {r['d']} reason {r['reason']}", None))
    for r in db.query("SELECT promo_id, category, region, CAST(start_date AS VARCHAR) s, CAST(end_date AS VARCHAR) e FROM v_promotions"):
        out.append((r["promo_id"], f"v_promotions {r['promo_id']} promotion category {r['category']} region {r['region']} {r['s']} {r['e']}", {"promo": True}))
    for r in db.query("SELECT order_id, category, region, CAST(order_date AS VARCHAR) d, promo_id FROM v_orders WHERE order_date BETWEEN ? AND ?", [b0, p1]):
        out.append((r["order_id"], f"v_orders {r['order_id']} {r['d']} category {r['category']} region {r['region']} promo {r['promo_id']}", None))
    return out


def run_baseline(inp: dict, token_budget: int = TOKEN_BUDGET) -> dict:
    db = SampleBackend(inp.get("dataset"))
    docs = rows_as_text(db, inp)
    scores = bm25([d[1] for d in docs], inp["query"])
    ranked = sorted(range(len(docs)), key=lambda i: (-scores[i], docs[i][0]))
    ctx, used = [], 0
    for i in ranked:
        n = len(docs[i][1].split())
        if used + n > token_budget:
            break
        ctx.append(docs[i]); used += n
    if provider() != "sample":
        r = llm.complete([{"role": "system", "content": f"Answer from the rows only. Reply with JSON only: {{\"label\": one of {TAXONOMY}, \"row_ids\": [ids]}}."},
                          {"role": "user", "content": inp["query"] + "\nRows:\n" + "\n".join(d[1] for d in ctx)}], "s2", 300)
        try:
            lab = _json(r["content"]).get("label")
        except Exception:
            lab = None
        return {"label": lab if lab in TAXONOMY else "none", "context_tokens": used, "provider": r["provider"]}
    late = [d[2] for d in ctx if d[2] and "carrier" in d[2] and not d[2]["on_time"]]
    lab = "none"
    if late:
        (seg, k), = Counter((x["carrier"], x["region"]) for x in late).most_common(1)
        if k / len(late) >= 0.5:
            lab = "carrier_sla_breach"
    if lab == "none" and any(d[2] and d[2].get("promo") for d in ctx):
        lab = "promotion_effect"
    return {"label": lab, "context_tokens": used, "provider": "sample"}
