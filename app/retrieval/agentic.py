"""Agentic Retriever (diagram v6.3): per hypothesis, a bounded tool-using loop.

The model (Lightning, thinking off) picks the next tool from a fixed whitelist, judges whether the
evidence is sufficient, and reformulates text queries. It never writes SQL: every tool is a
parameterised template over the 5 Zetaris views and every argument is validated against an
allow-list or against values read from the data. Hard caps: model-chosen steps per hypothesis,
model calls and tokens per round. Each tool call is traced (retriever/tool_call) and written to
H-MEM as a `retrieval` evidence node linked to its hypothesis.

The mandatory seed step per hypothesis is the deterministic tool the Evidence Evaluator relies on,
so the rule path is always covered. In SAMPLE_MODE, or when a model step fails or proposes an
invalid tool, the deterministic policy is used and the trace says so. Sufficiency here only
stops retrieval; support/refute is still decided by the Evidence Evaluator (with its own requery
loop, max 3 rounds) and claims by the deterministic Claim Gate.
"""
from __future__ import annotations
import json, re
from datetime import date
from ..agents.core import DIMS
from . import hybrid

TOOLS = {
    "segment_stats": "late/total shipments per segment, baseline vs period. args: {\"dims\": subset of [\"carrier\",\"region\"]}",
    "drill_down": "late/total for one segment, optional date sub-range inside the period. args: {\"carrier\"?: str, \"region\"?: str, \"date_from\"?: YYYY-MM-DD, \"date_to\"?: YYYY-MM-DD}",
    "promotions_overlap": "promotions active in the period. args: {}",
    "text_search": "hybrid BM25+embedding search over support-ticket text in the period. args: {\"query\": str, \"carrier\"?: str, \"region\"?: str}",
}
CAPS = {"model_steps_per_hyp": 2, "model_calls_per_round": 8, "tokens_per_round": 8000, "text_top_k": 30}
DEFAULT_TEXT_QUERY = "late delayed delivery not delivered missed tracking"
SEED = {"segment": "segment_stats", "seasonal": "segment_stats", "promotion": "promotions_overlap"}


class ToolError(ValueError):
    pass


class AgenticRetriever:
    name = "retriever"

    def __init__(self, db, base, log=None):
        """base: the deterministic Retriever (reused templates). log(event, **data): trace sink."""
        self.db, self.base, self.log = db, base, log or (lambda *a, **k: None)
        self._values: dict[str, set] = {}
        self.stats = {"tool_calls": 0, "model_steps": 0, "fallback_steps": 0, "rejected": 0, "tokens": 0}

    # ---------- whitelisted tools (templated SQL only) ----------
    def values(self, dim: str) -> set:
        if dim not in DIMS:
            raise ToolError(f"unknown dimension {dim!r}")
        if dim not in self._values:
            self._values[dim] = {r[dim] for r in self.db.query(f"SELECT DISTINCT {dim} FROM v_logistics")}
        return self._values[dim]

    def _seg(self, args: dict) -> dict:
        seg = {}
        for d in DIMS:
            if args.get(d) not in (None, ""):
                v = str(args[d])
                if v not in self.values(d):
                    raise ToolError(f"{d}={v!r} not in data")
                seg[d] = v
        return seg

    def validate(self, tool: str, args: dict, q: dict) -> dict:
        if tool not in TOOLS:
            raise ToolError(f"tool {tool!r} not in whitelist")
        args = args if isinstance(args, dict) else {}
        if tool == "segment_stats":
            dims = args.get("dims") or []
            dims = [dims] if isinstance(dims, str) else dims
            if not dims or any(d not in DIMS for d in dims):
                raise ToolError("dims must be a non-empty subset of carrier/region")
            return {"dims": sorted(set(dims))}
        if tool == "promotions_overlap":
            return {}
        if tool == "drill_down":
            out = {"segment": self._seg(args)}
            p0, p1 = date.fromisoformat(str(q["period"][0])), date.fromisoformat(str(q["period"][1]))
            for k, dflt in (("date_from", p0), ("date_to", p1)):
                v = args.get(k)
                try:
                    d = date.fromisoformat(str(v)) if v else dflt
                except ValueError:
                    raise ToolError(f"{k} not a date")
                out[k] = str(min(max(d, p0), p1))
            if out["date_from"] > out["date_to"]:
                raise ToolError("empty date range")
            return out
        query = re.sub(r"[^\w\s\-]", " ", str(args.get("query") or ""))[:200].strip()
        if not query:
            raise ToolError("empty query")
        return {"query": query, "segment": self._seg(args)}

    def run_tool(self, tool: str, a: dict, h: dict, q: dict) -> list[dict]:
        if tool == "segment_stats":
            return self.base.chunks_for({**h, "dims": a["dims"], "type": "seasonal" if h["type"] == "seasonal" else "segment"}, q)
        if tool == "promotions_overlap":
            return self.base.chunks_for({**h, "type": "promotion"}, q)
        if tool == "drill_down":
            seg, (b0, b1) = a["segment"], q["baseline"]
            w = "".join(f" AND {d} = ?" for d in seg)
            r = self.db.query("SELECT SUM(CASE WHEN ship_date BETWEEN ? AND ? THEN 1 ELSE 0 END) n_b, "
                              "SUM(CASE WHEN ship_date BETWEEN ? AND ? AND NOT on_time THEN 1 ELSE 0 END) late_b, "
                              "SUM(CASE WHEN ship_date BETWEEN ? AND ? THEN 1 ELSE 0 END) n_p, "
                              "SUM(CASE WHEN ship_date BETWEEN ? AND ? AND NOT on_time THEN 1 ELSE 0 END) late_p "
                              f"FROM v_logistics WHERE TRUE{w}",
                              [b0, b1, b0, b1, a["date_from"], a["date_to"], a["date_from"], a["date_to"], *seg.values()])[0]
            r = {k: (v or 0) for k, v in r.items()}
            return [{"hyp": h["id"], "view": "v_logistics", "segment": seg, "stats": r, "drill": True,
                     "text": (f"view v_logistics drill-down segment {seg} {a['date_from']}..{a['date_to']} late shipments on time delivery "
                              f"baseline n={r['n_b']} late={r['late_b']} period n={r['n_p']} late={r['late_p']}")}]
        seg = a["segment"]
        w = "".join(f" AND l.{d} = ?" for d in seg)
        rows = self.db.query("SELECT t.ticket_id, t.text, l.carrier, l.region FROM v_tickets t JOIN v_logistics l USING(order_id) "
                             f"WHERE t.created_date BETWEEN ? AND ?{w}", [q["period"][0], q["period"][1], *seg.values()])
        hits, meta = hybrid.search(rows, a["query"], "ticket_id", top_k=CAPS["text_top_k"])
        self._last_meta = meta
        if not hits:
            return []
        return [{"hyp": h["id"], "view": "v_tickets", "tickets": hits, "retrieval": meta,
                 "text": f"view v_tickets late delivery complaints query '{a['query']}' " + " ".join(t["text"] for t in hits)}]

    # ---------- the loop ----------
    def _call(self, tool, args, h, q, mem, rnd, source, why=""):
        try:
            a = self.validate(tool, args, q)
        except (ToolError, ValueError) as e:
            self.stats["rejected"] += 1
            self.log("tool_rejected", round=rnd, hyp=h["id"], tool=tool, args=args, source=source, reason=str(e))
            return None
        self._last_meta = None
        out = self.run_tool(tool, a, h, q)
        self.stats["tool_calls"] += 1
        rows = sum(len(c.get("tickets", [])) or len(c.get("cells", [])) or 1 for c in out)
        self.log("tool_call", round=rnd, hyp=h["id"], tool=tool, args=a, source=source, why=why[:200], chunks=len(out), rows=rows,
                 retrieval=self._last_meta)
        if mem is not None:
            nid = mem.add_node(f"R{len(mem.nodes)}", "retrieval", source=self.name, tool=tool,
                               text=f"{tool} {a} for {h['id']}: {len(out)} chunks, {rows} rows")
            if h["id"] in mem.nodes:
                mem.add_edge(nid, h["id"], "retrieved_for", source=self.name)
        return out

    @staticmethod
    def summary(chunks: list[dict]) -> str:
        return " | ".join(c["text"][:220] for c in chunks[-4:])

    def retrieve(self, hyps: list[dict], q: dict, mem=None, ctx=None, feedback: dict | None = None, rnd: int = 1) -> list[dict]:
        from ..agents import llm_steps
        chunks, seen = [], set()
        budget = {"calls": 0, "tokens": 0}

        def add(out):
            for c in out or []:
                k = (c["hyp"], c["view"], c["text"])
                if k not in seen:
                    seen.add(k); chunks.append(c)

        for h in hyps:
            mine0 = len(chunks)
            add(self._call(SEED[h["type"]], {"dims": h.get("dims") or DIMS}, h, q, mem, rnd, "policy:seed"))
            live = bool(ctx and ctx.live)
            steps, tried = 0, [f"{SEED[h['type']]}({h.get('dims') or ''})"]
            while live and steps < CAPS["model_steps_per_hyp"]:
                if budget["calls"] >= CAPS["model_calls_per_round"] or budget["tokens"] >= CAPS["tokens_per_round"]:
                    self.log("cap_reached", round=rnd, hyp=h["id"], **budget)
                    break
                n0 = len(ctx.calls)
                dec = ctx.attempt(self.name, llm_steps.retrieval_step, q["query"], h["text"], (feedback or {}).get("gap", ""),
                                  "Already called: " + "; ".join(tried) + " || " + self.summary(chunks[mine0:]), TOOLS, {d: sorted(map(str, self.values(d))) for d in DIMS})
                budget["calls"] += 1
                for c in ctx.calls[n0:]:
                    budget["tokens"] += ((c.get("usage") or {}).get("total_tokens") or 0)
                steps += 1
                if not dec:
                    self.stats["fallback_steps"] += 1
                    self.log("model_step_failed", round=rnd, hyp=h["id"], fallback="deterministic policy")
                    live = False
                    break
                self.stats["model_steps"] += 1
                self.log("agent_decision", round=rnd, hyp=h["id"], decision=dec)
                if dec.get("sufficient") or not dec.get("tool"):
                    break
                sig = f"{dec['tool']}({json.dumps(dec.get('args') or {}, sort_keys=True)})"
                if sig in tried:
                    self.log("repeat_call_stopped", round=rnd, hyp=h["id"], call=sig)
                    break
                tried.append(sig)
                add(self._call(dec["tool"], dec.get("args") or {}, h, q, mem, rnd, "model", dec.get("why", "")))
        # deterministic policy, always: the ticket complaint search the baseline Retriever ran (now hybrid)
        tk = {"id": "H_tickets", "type": "tickets", "text": "late delivery complaints"}
        add(self._call("text_search", {"query": DEFAULT_TEXT_QUERY}, tk, q, mem, rnd, "policy"))
        self.stats["tokens"] += budget["tokens"]
        return chunks
