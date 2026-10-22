"""Orchestrator: Planner -> Retriever -> S1 Filter -> Evidence Evaluator (loop to Planner, max 3)
-> Cause Analyst -> Writer -> Claim Gate (loop to Cause Analyst, max 2) -> memo + confidence."""
from __future__ import annotations
import re, time, uuid
from .adapters.zetaris import get_backend
from .agents.core import Planner, Retriever, S1Filter, EvidenceEvaluator, CauseAnalyst, Writer, ClaimGate
from .confidence import confidence
from .config import CAPS, TIMEOUTS, provider
from .memory import HMem, Markovian
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
    w = " AND ".join(f"l.{c} = ?" for c in seg)
    vals = list(seg.values())
    det = {}
    def rate(sql, win):
        r = db.query(sql, [*vals, *win])[0]
        return (r["k"] or 0) / r["n"] if r["n"] else None
    checks = {
        "v_logistics": f"SELECT COUNT(*) n, SUM(CASE WHEN NOT l.on_time THEN 1 ELSE 0 END) k FROM v_logistics l WHERE {w} AND l.ship_date BETWEEN ? AND ?",
        "v_tickets": f"SELECT COUNT(*) n, COUNT(t.ticket_id) k FROM v_logistics l LEFT JOIN v_tickets t USING(order_id) WHERE {w} AND l.ship_date BETWEEN ? AND ?",
        "v_returns": f"SELECT COUNT(*) n, SUM(CASE WHEN r.reason='late_delivery' THEN 1 ELSE 0 END) k FROM v_logistics l LEFT JOIN v_returns r USING(order_id) WHERE {w} AND l.ship_date BETWEEN ? AND ?",
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
    tr.log("orchestrator", "start", provider=provider())
    q = parse_question(inp)
    db = get_backend()
    tr.log("orchestrator", "backend", name=db.name)
    mem, mk = HMem(), Markovian()
    planner, retr, s1 = Planner(), Retriever(db), S1Filter()
    ev, analyst, writer, gate = EvidenceEvaluator(db, retr), CauseAnalyst(), Writer(db), ClaimGate(db)
    feedback, all_verdicts, status = None, [], "success"
    for rnd in range(1, CAPS["evaluator_rounds"] + 1):
        hyps = planner.plan(q, mem, feedback)
        tr.log(planner.name, "hypotheses", round=rnd, hypotheses=[h["id"] for h in hyps], revised=bool(feedback))
        chunks = retr.retrieve(hyps, q)
        tr.log(retr.name, "retrieved", round=rnd, chunks=len(chunks))
        kept, proj, act = s1.run(chunks, mem)
        mk.record(rnd, proj, act)
        tr.log(s1.name, "filtered", round=rnd, kept=len(kept), dropped=len(chunks) - len(kept), projected_tokens=proj, actual_tokens=act)
        res = ev.evaluate(hyps, kept, q, mem)
        all_verdicts += res["verdicts"]
        tr.log(ev.name, "verdicts", round=rnd, verdicts=res["verdicts"], feedback=res["feedback"])
        feedback = res["feedback"]
        if not feedback:
            break
        tr.log(ev.name, "send_back_to_planner", round=rnd, reason=feedback["gap"])
        if time.time() - t0 > TIMEOUTS["run_s"]:
            break
    else:
        status = "partial"
    if feedback:
        status = "partial"
    blocked: set[str] = set()
    proposed: dict[str, dict] = {}
    results = []
    for g in range(CAPS["claim_gate_rounds"] + 1):
        analysis = analyst.analyse(all_verdicts, blocked)
        tr.log(analyst.name, "ranked", top_cause_label=analysis["top_cause_label"], causes=analysis["causes"])
        claims = writer.write(analysis, q, blocked)
        for c in claims:
            proposed[c["id"]] = c
        tr.log(writer.name, "claims", claims=[c["id"] for c in claims])
        results = gate.check(claims)
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
    out = {"question": q, "analysis": analysis, "claims": [proposed[i] for i in proposed if i in passed],
           "blocked_claims": sorted(set(proposed) - passed), "confidence": conf, "token_report": mk.report(),
           "resolution": "resolved" if status == "success" else "unresolved",
           "evidence_graph": {"backend": mem.backend, "nodes": len(mem.nodes), "edges": len(mem.edges)}}
    out["memo_md"] = render_memo(out, run_id)
    memo_path = tr.path.parent / f"memo-{run_id}.md"
    memo_path.write_text(out["memo_md"])
    tr.log("orchestrator", "end", status=status, confidence=conf["confidence"])
    return {"run_id": run_id, "status": status, "output": {"summary": out["memo_md"].splitlines()[1],
            "result": out, "artifacts": [str(memo_path.relative_to(tr.path.parents[1]))]},
            "agents": [{"name": a.name} for a in (planner, retr, s1, ev, analyst, writer, gate)],
            "trace_id": tr.trace_id, "log_file": f"logs/{tr.path.name}", "execution_time_seconds": round(time.time() - t0, 3)}
