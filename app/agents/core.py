"""Agents (SAMPLE provider path: deterministic, real computation over the views, no LLM).

Each agent has its own inputs, tools, output schema and authority (see docs/ARCHITECTURE.md).
"""
from __future__ import annotations
from ..bm25 import bm25, tok
from ..memory import HMem, count_tokens
from . import llm_steps


class LLMCtx:
    """live=False in SAMPLE_MODE: no model is called. Records every model call for the trace."""
    def __init__(self, live: bool):
        self.live, self.calls = live, []

    def attempt(self, agent: str, fn, *a):
        if not self.live:
            return None
        try:
            out, meta = fn(*a)
            metas = meta if isinstance(meta, list) else [meta]
            for m in metas:
                self.calls.append({"agent": agent, "provider": m.get("provider"), "model": m.get("model"), "ok": True, "usage": m.get("usage")})
            return out
        except Exception as e:  # fall back to the deterministic path, logged
            self.calls.append({"agent": agent, "ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "fallback": "deterministic"})
            return None

TAXONOMY = ["carrier_sla_breach", "supplier_cost_increase", "promotion_effect", "seasonality", "stockout", "none"]
DIMS = ["carrier", "region"]


class Planner:
    """Writes competing hypotheses + query plans into H-MEM. Revises on Evaluator feedback."""
    name = "planner"

    def plan(self, q: dict, mem: HMem, feedback: dict | None, ctx: "LLMCtx | None" = None, memory_context: str = "") -> list[dict]:
        if feedback and feedback.get("drill"):
            dims = feedback["drill"]
            hyps = [{"id": "H_" + "_x_".join(dims), "type": "segment", "dims": dims,
                     "text": f"Late shipments concentrated in one {' x '.join(dims)} segment"}]
        else:
            hyps = [{"id": f"H_{d}", "type": "segment", "dims": [d],
                     "text": f"On-time drop concentrated in one {d}"} for d in DIMS]
            hyps.append({"id": "H_promo", "type": "promotion", "dims": [],
                         "text": "A promotion active in the period caused the drop"})
            chosen = ctx.attempt(self.name, llm_steps.plan, q["query"], memory_context) if ctx else None
            if chosen:
                hyps = [h for h in hyps if h["id"] in chosen]
        for h in hyps:
            mem.add_node(h["id"], "hypothesis", source=self.name, text=h["text"])
        return hyps


class Retriever:
    """Runs SQL over the 5 views + BM25 over ticket text. Only this agent and the Evaluator query data."""
    name = "retriever"

    def __init__(self, db):
        self.db = db

    def segment_stats(self, dims: list[str], q: dict) -> list[dict]:
        g = ", ".join(dims)
        sql = (f"SELECT {g}, "
               "SUM(CASE WHEN ship_date BETWEEN ? AND ? THEN 1 ELSE 0 END) AS n_b, "
               "SUM(CASE WHEN ship_date BETWEEN ? AND ? AND NOT on_time THEN 1 ELSE 0 END) AS late_b, "
               "SUM(CASE WHEN ship_date BETWEEN ? AND ? THEN 1 ELSE 0 END) AS n_p, "
               "SUM(CASE WHEN ship_date BETWEEN ? AND ? AND NOT on_time THEN 1 ELSE 0 END) AS late_p "
               f"FROM v_logistics GROUP BY {g} ORDER BY {g}")
        b, p = q["baseline"], q["period"]
        return self.db.query(sql, [b[0], b[1], b[0], b[1], p[0], p[1], p[0], p[1]])

    def retrieve(self, hyps: list[dict], q: dict) -> list[dict]:
        chunks = []
        for h in hyps:
            if h["type"] == "segment":
                for r in self.segment_stats(h["dims"], q):
                    seg = {d: r[d] for d in h["dims"]}
                    txt = (f"view v_logistics segment {seg} late shipments on time delivery "
                           f"baseline n={r['n_b']} late={r['late_b']} period n={r['n_p']} late={r['late_p']}")
                    chunks.append({"hyp": h["id"], "view": "v_logistics", "segment": seg, "stats": r, "text": txt})
            elif h["type"] == "promotion":
                for pr in self.db.query("SELECT promo_id, category, region, CAST(start_date AS VARCHAR) s, CAST(end_date AS VARCHAR) e "
                                        "FROM v_promotions WHERE start_date <= ? AND end_date >= ?", [q["period"][1], q["period"][0]]):
                    chunks.append({"hyp": h["id"], "view": "v_promotions", "promo": pr,
                                   "text": f"view v_promotions promotion {pr['promo_id']} category {pr['category']} region {pr['region']} {pr['s']}..{pr['e']}"})
        tickets = self.db.query("SELECT t.ticket_id, t.text, l.carrier, l.region FROM v_tickets t JOIN v_logistics l USING(order_id) "
                                "WHERE t.created_date BETWEEN ? AND ?", [q["period"][0], q["period"][1]])
        scores = bm25([t["text"] for t in tickets], "late delayed delivery not delivered missed tracking")
        top = [t for t, s in sorted(zip(tickets, scores), key=lambda x: -x[1]) if s > 0][:30]
        if top:
            chunks.append({"hyp": "H_tickets", "view": "v_tickets", "tickets": top,
                           "text": "view v_tickets late delivery complaints " + " ".join(t["text"] for t in top)})
        return chunks


class S1Filter:
    """Deterministic lexical+signal relevance filter (sample path for the S1 model). Consolidates kept chunks into H-MEM."""
    name = "s1_filter"
    TERMS = set(tok("late on time delivery shipments promotion complaints"))

    KEYS = {"v_logistics": TERMS, "v_promotions": {"promotion"}, "v_tickets": {"late", "delivery"}}

    def score(self, c: dict) -> float:
        keys = self.KEYS[c["view"]]
        lex = len(keys & set(tok(c["text"]))) / len(keys)
        if c["view"] == "v_logistics":
            s = c["stats"]
            rb = s["late_b"] / s["n_b"] if s["n_b"] else 0
            excess = s["late_p"] - s["n_p"] * rb
            return lex if excess > 0 else 0.0
        return lex

    def run(self, chunks: list[dict], mem: HMem, threshold: float = 0.3, ctx: "LLMCtx | None" = None, question: str = "") -> tuple[list[dict], int, int]:
        kept = []
        live = ctx.attempt(self.name, llm_steps.s1_scores, [c["text"] for c in chunks], question) if ctx and chunks else None
        for i, c in enumerate(chunks):
            c["relevance"] = round(live[i] if live else self.score(c), 3)
            if c["relevance"] >= threshold:
                kept.append(c)
                nid = mem.add_node(f"E{len(mem.nodes)}", "evidence", source=self.name, view=c["view"], text=c["text"][:200])
                c["node"] = nid
        return kept, sum(count_tokens(c["text"]) for c in chunks), sum(count_tokens(c["text"]) for c in kept)


class EvidenceEvaluator:
    """Marks evidence supports/refutes/gap, re-querying the data itself. Can send the Planner back."""
    name = "evidence_evaluator"

    def __init__(self, db, retriever: Retriever):
        self.db, self.r = db, retriever

    def evaluate(self, hyps, kept, q, mem: HMem, ctx: "LLMCtx | None" = None) -> dict:
        tot = self.db.query("SELECT SUM(CASE WHEN ship_date BETWEEN ? AND ? THEN 1 ELSE 0 END) n_b, "
                            "SUM(CASE WHEN ship_date BETWEEN ? AND ? AND NOT on_time THEN 1 ELSE 0 END) l_b, "
                            "SUM(CASE WHEN ship_date BETWEEN ? AND ? THEN 1 ELSE 0 END) n_p, "
                            "SUM(CASE WHEN ship_date BETWEEN ? AND ? AND NOT on_time THEN 1 ELSE 0 END) l_p FROM v_logistics",
                            [*q["baseline"], *q["baseline"], *q["period"], *q["period"]])[0]
        base_rate = tot["l_b"] / tot["n_b"]
        total_excess = tot["l_p"] - tot["n_p"] * base_rate
        verdicts, supported = [], []
        for h in hyps:
            if h["type"] == "segment":
                rows = self.r.segment_stats(h["dims"], q)  # own re-query, not the Retriever's chunks
                best = max(rows, key=lambda r: r["late_p"] - r["n_p"] * base_rate)
                share = (best["late_p"] - best["n_p"] * base_rate) / total_excess if total_excess > 0 else 0
                rb = 100 * best["late_b"] / best["n_b"] if best["n_b"] else 0
                rp = 100 * best["late_p"] / best["n_p"] if best["n_p"] else 0
                seg = {d: best[d] for d in h["dims"]}
                v = "supports" if share >= 0.5 and rp - rb >= 5 else "refutes"
                verdicts.append({"hyp": h["id"], "verdict": v, "segment": seg, "share_of_excess_late": round(share, 3),
                                 "late_rate_baseline": round(rb, 2), "late_rate_period": round(rp, 2)})
                if v == "supports":
                    supported.append(h)
            else:
                promos = [c["promo"] for c in kept if c["view"] == "v_promotions"]
                for pr in promos:
                    r = self.db.query("SELECT COUNT(*) n, SUM(CASE WHEN NOT l.on_time THEN 1 ELSE 0 END) late FROM v_logistics l "
                                      "JOIN v_orders o USING(order_id) WHERE l.ship_date BETWEEN ? AND ? AND o.category=? AND o.region=?",
                                      [*q["period"], pr["category"], pr["region"]])[0]
                    exp = (r["n"] or 0) * base_rate
                    share = ((r["late"] or 0) - exp) / total_excess if total_excess > 0 else 0
                    v = "supports" if share >= 0.5 else "refutes"
                    verdicts.append({"hyp": h["id"], "verdict": v, "promo_id": pr["promo_id"], "dates_overlap": True,
                                     "share_of_excess_late": round(share, 3), "promo_shipments": r["n"], "promo_late": r["late"]})
                if not promos:
                    verdicts.append({"hyp": h["id"], "verdict": "gap", "reason": "no promotion overlaps the period"})
        if ctx and ctx.live:
            texts = {h["id"]: h["text"] for h in hyps}
            for v in verdicts:
                lv = ctx.attempt(self.name, llm_steps.verdict, texts.get(v["hyp"], v["hyp"]), {k: x for k, x in v.items() if k not in ("hyp", "verdict")})
                if lv:
                    v["rule_verdict"], v["verdict"] = v["verdict"], lv
            supported = [h for h in hyps if any(v["hyp"] == h["id"] and v["verdict"] == "supports" for v in verdicts)]
        for v in verdicts:
            ev = [c["node"] for c in kept if c["hyp"] == v["hyp"] and "node" in c]
            for e in ev or [mem.add_node(f"E{len(mem.nodes)}", "evidence", view="evaluator_requery", text=str(v))]:
                mem.add_edge(e, v["hyp"], v["verdict"])
        feedback = None
        seg_sup = [h for h in supported if h["type"] == "segment"]
        if len(seg_sup) >= 2 and all(len(h["dims"]) == 1 for h in seg_sup):
            feedback = {"gap": "two single-dimension hypotheses both supported", "drill": sorted(d for h in seg_sup for d in h["dims"])}
        return {"verdicts": verdicts, "feedback": feedback, "base_rate_pp": round(100 * base_rate, 2),
                "total_excess_late": round(total_excess, 1), "totals": tot}


class CauseAnalyst:
    """Ranks causes with a deterministic decomposition and picks top_cause_label from the taxonomy."""
    name = "cause_analyst"

    def analyse(self, all_verdicts: list[dict], blocked: set[str], ctx: "LLMCtx | None" = None) -> dict:
        seg = [v for v in all_verdicts if v["verdict"] == "supports" and "segment" in v]
        seg.sort(key=lambda v: (-len(v["segment"]), -v["share_of_excess_late"]))
        causes = [{"segment": v["segment"], "hyp": v["hyp"], "estimated_contribution": min(1.0, v["share_of_excess_late"]),
                   "raw_share_of_excess_late": v["share_of_excess_late"],
                   "label": "carrier_sla_breach" if "carrier" in v["segment"] else "none"} for v in seg]
        discarded = [v for v in all_verdicts if v["verdict"] == "refutes" and "promo_id" in v]
        top = causes[0] if causes else None
        lab = top["label"] if top else "none"
        if top and ctx:
            lab = ctx.attempt(self.name, llm_steps.label, causes) or lab
            top["label"] = lab
        return {"causes": causes, "top_cause": top, "top_cause_label": lab,
                "discarded": discarded, "blocked": sorted(blocked)}


class Writer:
    """Writes claims only from Analyst output, each with row IDs and a checkable metric."""
    name = "writer"

    def __init__(self, db):
        self.db = db

    def write(self, analysis: dict, q: dict, blocked: set[str]) -> list[dict]:
        claims = []
        top = analysis["top_cause"]
        if top:
            w = "AND ".join(f"{c} = ? " for c in top["segment"])
            rows = self.db.query(f"SELECT shipment_id FROM v_logistics WHERE {w} AND ship_date BETWEEN ? AND ? AND NOT on_time ORDER BY shipment_id LIMIT 5",
                                 [*top["segment"].values(), *q["period"]])
            ids = [r["shipment_id"] for r in rows]
            from ..checks.claims import metric_value
            for name, win in (("period", q["period"]), ("baseline", q["baseline"])):
                v = metric_value(self.db, "on_time_rate", top["segment"], win)
                cid = f"C_ontime_{name}"
                if cid in blocked or v is None:
                    continue
                rid = ids if name == "period" else [r["shipment_id"] for r in self.db.query(
                    f"SELECT shipment_id FROM v_logistics WHERE {w} AND ship_date BETWEEN ? AND ? ORDER BY shipment_id LIMIT 5", [*top["segment"].values(), *win])]
                claims.append({"id": cid, "metric": "on_time_rate", "segment": top["segment"], "window": win,
                               "value": round(v, 2), "row_ids": rid,
                               "text": f"On-time rate for {', '.join(f'{k}={x}' for k, x in top['segment'].items())} was {round(v, 1)}% in the {name} window ({win[0]}..{win[1]})."})
        return claims


class ClaimGate:
    """Deterministic (no LLM). Decides what leaves the system; can reject the Writer's output."""
    name = "claim_gate"

    def __init__(self, db):
        self.db = db

    def check(self, claims: list[dict]) -> list[dict]:
        from ..checks.claims import check_claim
        return [check_claim(self.db, c) for c in claims]
