"""Orchestrator: Planner -> Retriever -> S1 Filter -> Evidence Evaluator (loop to Planner, max 3)
-> Cause Analyst -> Writer -> Claim Gate (loop to Cause Analyst, max 2) -> memo + confidence."""
from __future__ import annotations
import re, time, uuid
from .adapters.zetaris import get_backend
from .agents.core import Planner, Retriever, S1Filter, EvidenceEvaluator, CauseAnalyst, Writer, ClaimGate
from .confidence import confidence
from .config import CAPS, TIMEOUTS, provider
from .memory import HMem, count_tokens
from .meterless import Bridge
from .agents.core import LLMCtx
from .agents import llm_steps
from .checks.claims import check_narrative
from .trace import Tracer
from .memo import render_memo

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_question(inp: dict) -> dict:
    q = {"query": inp.get("query", ""), "kpi": inp.get("kpi"), "period": inp.get("period"), "baseline": inp.get("baseline")}
    if not q["kpi"] and re.search(r"on[- ]time", q["query"], re.I):
        q["kpi"] = "on_time_rate"
    if not (q["period"] and q["baseline"]):
        d = DATE.findall(q["query"])
        if len(d) == 4:
            q["baseline"], q["period"] = d[:2], d[2:]
    if q["kpi"] != "on_time_rate" or not q["period"] or not q["baseline"]:
        raise ValueError("Day-1 build supports KPI on_time_rate with explicit baseline and period dates (YYYY-MM-DD)")
    return q


def view_agreement(db, seg: dict, q: dict) -> tuple[int, int, dict]:
    from .checks.claims import SEG_COLS
    w = " AND ".join(f"{SEG_COLS[c]} = ?" for c in seg)
    vals = list(seg.values())
    det = {}
    def rate(sql, win):
        r = db.query(sql, [*vals, *win])[0]
        return (r["k"] or 0) / r["n"] if r["n"] else None
    checks = {
        "v_logistics": f"SELECT COUNT(*) n, SUM(CASE WHEN NOT l.on_time THEN 1 ELSE 0 END) k FROM v_logistics l JOIN v_orders o USING(order_id) WHERE {w} AND l.ship_date BETWEEN ? AND ?",
        "v_tickets": f"SELECT COUNT(*) n, COUNT(t.ticket_id) k FROM v_logistics l JOIN v_orders o USING(order_id) LEFT JOIN v_tickets t USING(order_id) WHERE {w} AND l.ship_date BETWEEN ? AND ?",
        "v_returns": f"SELECT COUNT(*) n, SUM(CASE WHEN r.reason='late_delivery' THEN 1 ELSE 0 END) k FROM v_logistics l JOIN v_orders o USING(order_id) LEFT JOIN v_returns r USING(order_id) WHERE {w} AND l.ship_date BETWEEN ? AND ?",
    }
    agree = relevant = 0
    for v, sql in checks.items():
        b, p = rate(sql, q["baseline"]), rate(sql, q["period"])
        if b is None or p is None:
            det[v] = "no relevant rows"; continue
        relevant += 1
        ok = p > b
        agree += ok
        det[v] = {"baseline_rate": round(b, 4), "period_rate": round(p, 4), "agrees": ok}
    promo = db.query("SELECT COUNT(*) n FROM v_promotions p WHERE p.start_date <= ? AND p.end_date >= ? AND p.region = ?",
                     [q["period"][1], q["period"][0], seg.get("region", "")])[0]["n"]
    det["v_promotions"] = "no promotion overlaps the top-cause segment" if not promo else {"overlapping_promos": promo, "agrees": False}
    if promo:
        relevant += 1
    det["v_orders"] = "not used for direction in this build"
    return agree, relevant, det


def run(inp: dict, run_id: str | None = None) -> dict:
    t0 = time.time()
    run_id = run_id or uuid.uuid4().hex[:12]
    tr = Tracer(run_id)
    prov = provider()
    ctx = LLMCtx(live=prov != "sample")
    tr.log("orchestrator", "start", provider=prov)
    q = parse_question(inp)
    db = get_backend(inp.get("dataset"))
    try:
        bridge = Bridge()
        bridge.call("reset")
    except Exception as e:
        bridge = None
        tr.log("orchestrator", "meterless_unavailable", error=str(e))
    tr.log("orchestrator", "backend", data=db.name, meterless="bridge" if bridge else "local-fallback")
    try:
        return _run(inp, q, db, bridge, tr, ctx, t0, run_id)
    finally:
        if bridge:
            bridge.close()


def _run(inp, q, db, bridge, tr, ctx, t0, run_id) -> dict:
    mem = HMem(bridge)
    planner, retr, s1 = Planner(), Retriever(db), S1Filter()
    ev, analyst, writer, gate = EvidenceEvaluator(db, retr), CauseAnalyst(), Writer(db), ClaimGate(db)
    st = {"feedback": None, "verdicts": [], "rounds": [], "done": False}

    def investigate_round(step: int, carryover: str) -> str:
        rnd = step + 1
        n0 = len(ctx.calls)
        hyps = planner.plan(q, mem, st["feedback"], ctx, carryover or mem.recall(q["query"]))
        tr.log(planner.name, "hypotheses", round=rnd, hypotheses=[h["id"] for h in hyps], revised=bool(st["feedback"]))
        chunks = retr.retrieve(hyps, q)
        tr.log(retr.name, "retrieved", round=rnd, chunks=len(chunks))
        kept, proj, act = s1.run(chunks, mem, ctx=ctx, question=q["query"])
        st["rounds"].append({"round": rnd, "s1_projected_tokens": proj, "s1_actual_tokens": act})
        tr.log(s1.name, "filtered", round=rnd, kept=len(kept), dropped=len(chunks) - len(kept), projected_tokens=proj, actual_tokens=act)
        res = ev.evaluate(hyps, kept, q, mem, ctx)
        st["verdicts"] += res["verdicts"]
        tr.log(ev.name, "verdicts", round=rnd, verdicts=res["verdicts"], feedback=res["feedback"])
        for c in ctx.calls[n0:]:
            tr.log(c["agent"], "model_call", round=rnd, call=c)
        st["feedback"] = res["feedback"]
        summary = "; ".join(f"{v['hyp']}={v['verdict']}" for v in res["verdicts"])
        if not st["feedback"] or time.time() - t0 > TIMEOUTS["run_s"]:
            st["done"] = not st["feedback"]
            return f"Round {rnd}: {summary}. [TASK_COMPLETE]"
        tr.log(ev.name, "send_back_to_planner", round=rnd, reason=st["feedback"]["gap"])
        return (f"Round {rnd}: {summary}.\n[STATE_CHECKPOINT]\nCOMPLETED: round {rnd}\nREMAINING: drill {st['feedback']['drill']}\n"
                f"DECISIONS: {summary}\nCONTEXT: {q['query']}")

    if bridge:
        mk = bridge.call("markovian.run", on_step=lambda m: investigate_round(m["step"], m["carryover"]),
                         goal=q["query"], memoryContext=mem.recall(q["query"]), maxChunks=CAPS["evaluator_rounds"])
        tr.log("markovian", "run", **{k: mk[k] for k in ("status", "chunks", "totalTokensUsed", "totalTokensSaved", "tokenLabel")})
    else:
        mk = {"status": "local-fallback"}
        for step in range(CAPS["evaluator_rounds"]):
            if "[TASK_COMPLETE]" in investigate_round(step, ""):
                break
    status = "success" if st["done"] else "partial"
    blocked: set[str] = set()
    proposed: dict[str, dict] = {}
    results, narrative = [], None
    for g in range(CAPS["claim_gate_rounds"] + 1):
        n0 = len(ctx.calls)
        analysis = analyst.analyse(st["verdicts"], blocked, ctx)
        tr.log(analyst.name, "ranked", top_cause_label=analysis["top_cause_label"], causes=analysis["causes"])
        claims = writer.write(analysis, q, blocked)
        for c in claims:
            proposed[c["id"]] = c
        narrative = None
        if ctx.live and "narrative" not in blocked:
            narrative = ctx.attempt(writer.name, llm_steps.narrative, claims, analysis["discarded"])
            if narrative:
                proposed["narrative"] = {"id": "narrative", "text": narrative}
        for c in ctx.calls[n0:]:
            tr.log(c["agent"], "model_call", call=c)
        tr.log(writer.name, "claims", claims=[c["id"] for c in claims], narrative=bool(narrative))
        results = gate.check(claims)
        if narrative:
            src = [c["text"] for c in claims] + [str(d) for d in analysis["discarded"]] + [q["query"]]
            results.append(check_narrative(narrative, src))
        failed = [r for r in results if not r["passed"]]
        tr.log(gate.name, "checked", passed=[r["claim_id"] for r in results if r["passed"]], blocked=[{"id": r["claim_id"], "reasons": r["reasons"]} for r in failed])
        if not failed:
            break
        blocked |= {r["claim_id"] for r in failed}
        if g == CAPS["claim_gate_rounds"]:
            status = "partial"
        else:
            tr.log(gate.name, "send_back_to_cause_analyst", blocked=sorted(blocked))
    passed = {r["claim_id"] for r in results if r["passed"]}
    if not analysis["top_cause"]:
        status = "partial"
    top = analysis["top_cause"]
    sup = len(mem.edges_to(top["hyp"], "supports")) if top else 0
    ref = len(mem.edges_to(top["hyp"], "refutes")) if top else 0
    agree, relevant, vdet = view_agreement(db, top["segment"], q) if top else (0, 0, {})
    conf = confidence(len(proposed), len(passed), agree, relevant, sup, ref, partial=status == "partial")
    conf["views"] = vdet
    ledger = mem.ledger()
    lpath = tr.path.parent / f"hmem-ledger-{run_id}.jsonl"
    lpath.write_text("".join(__import__("json").dumps(e, default=str) + "\n" for e in ledger["entries"]))
    proj = sum(r["s1_projected_tokens"] for r in st["rounds"]); act = sum(r["s1_actual_tokens"] for r in st["rounds"])
    out = {"question": q, "analysis": analysis, "claims": [proposed[i] for i in proposed if i in passed and i != "narrative"],
           "narrative": proposed["narrative"]["text"] if "narrative" in passed else None,
           "blocked_claims": sorted(set(proposed) - passed), "confidence": conf,
           "token_report": {"s1_filter": {"unit": "whitespace tokens (approx.)", "rounds": st["rounds"], "projected_total": proj,
                                          "actual_total": act, "avoided_by_s1": proj - act}, "markovian": mk},
           "model_calls": ctx.calls, "resolution": "resolved" if status == "success" else "unresolved",
           "evidence_graph": {"backend": mem.backend, "nodes": len(mem.nodes), "edges": len(mem.edges),
                              "hmem_ledger_entries": len(ledger["entries"]), "hmem_ledger_file": f"logs/{lpath.name}"}}
    out["memo_md"] = render_memo(out, run_id)
    memo_path = tr.path.parent / f"memo-{run_id}.md"
    memo_path.write_text(out["memo_md"])
    tr.log("orchestrator", "end", status=status, confidence=conf["confidence"])
    return {"run_id": run_id, "status": status, "output": {"summary": out["memo_md"].splitlines()[1],
            "result": out, "artifacts": [f"logs/{memo_path.name}", f"logs/{lpath.name}"]},
            "agents": [{"name": a.name} for a in (planner, retr, s1, ev, analyst, writer, gate)],
            "trace_id": tr.trace_id, "log_file": f"logs/{tr.path.name}", "execution_time_seconds": round(time.time() - t0, 3)}
