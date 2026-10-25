"""Deterministic Olist investigation -> trace -> verifiable memo. $0: no model calls.

Trace events (logs/trace-<run_id>.jsonl):
  start, query (one per SQL, with sql_sha + elapsed_ms), hypothesis_update (before/after/evidence_id,
  plus the comparison outcome and the source tables it used), ranked, memo, done.
Why-diff and sensitivity are computed ONLY from the hypothesis_update events in the trace file:
  why_diff     prior order and status of each hypothesis vs final status, with the evidence ids that moved it
  sensitivity  drop one source table, re-apply the same decision rule to the remaining recorded outcomes
               (no re-query, no re-planning), report whether the top cause changes. This is "sensitivity
               of the conclusion", not a full counterfactual re-run.
System time = last trace ts - first trace ts (measured, nothing estimated).
"""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from ..adapters.zetaris import badge
from ..config import ROOT
from ..trace import Tracer
from . import ATTRIBUTION
from .metrics import TABLES, metric_sql, spec, value, witnesses
from .questions import QUESTIONS, REFUTE_RATIO, SUPPORT_RATIO

FLIP = {"supports": "refutes", "refutes": "supports", "inconclusive": "inconclusive"}


def outcome(ratio: float | None) -> str:
    if ratio is None:
        return "inconclusive"
    return "supports" if ratio >= SUPPORT_RATIO else "refutes" if ratio <= REFUTE_RATIO else "inconclusive"


def combine(outcomes: list[str]) -> str:
    if not outcomes:
        return "open"
    if "refutes" in outcomes:
        return "refuted"
    return "supported" if all(o == "supports" for o in outcomes) else "inconclusive"


def _q(db, tr, metric, p, eid):
    sql, params = metric_sql(metric, p)
    t0 = time.time()
    v = value(db, metric, p)
    ids = witnesses(db, metric, p)
    tr.log("retriever", "query", evidence_id=eid, metric=metric, params=p, value=v,
           sql_sha=hashlib.sha256(json.dumps([sql, params]).encode()).hexdigest()[:16],
           elapsed_ms=round((time.time() - t0) * 1000, 1), backend=badge(db))
    return v, ids


def _claim(cid, metric, p, v, ids, label):
    return {"id": cid, "metric": metric, "params": p, "value": round(v, 3), "row_ids": ids, "label": label}


def top_cause(status: dict, score: dict) -> str | None:
    sup = [h for h, s in status.items() if s == "supported"]
    return max(sup, key=lambda h: (score.get(h) or 0, h)) if sup else None


def replay(updates: list[dict], drop: str | None = None) -> tuple[dict, dict]:
    """Re-apply the decision rule to recorded hypothesis_update outcomes, optionally without one source."""
    per, score, status = {}, {}, {}
    for u in updates:
        d = u["data"]
        status.setdefault(d["hyp"], "open")
        if d.get("evidence_id") is None:
            continue
        if drop and drop in d["sources"]:
            continue
        per.setdefault(d["hyp"], []).append(d["hyp_outcome"])
        score[d["hyp"]] = d["effect"]
    for h in status:
        status[h] = combine(per.get(h, []))
    return status, score


def why_diff(trace_path: Path) -> dict:
    ev = [json.loads(l) for l in Path(trace_path).read_text(encoding="utf-8").splitlines()]
    ups = [e for e in ev if e["event"] == "hypothesis_update"]
    prior = [e["data"]["hyp"] for e in ups if e["data"]["before"] is None]
    final, score = replay(ups)
    moved = {h: [e["data"]["evidence_id"] for e in ups if e["data"]["hyp"] == h and e["data"]["evidence_id"]
                 and e["data"]["before"] != e["data"]["after"]] for h in prior}
    rows = [{"hyp": h, "prior_rank": i + 1, "before": "open", "after": final[h], "moved_by": moved[h]} for i, h in enumerate(prior)]
    return {"prior_first": prior[0] if prior else None, "final_top": top_cause(final, score), "hypotheses": rows,
            "n_updates": len(ups), "source": f"{Path(trace_path).name}: hypothesis_update events only"}


def sensitivity(trace_path: Path) -> dict:
    ev = [json.loads(l) for l in Path(trace_path).read_text(encoding="utf-8").splitlines()]
    ups = [e for e in ev if e["event"] == "hypothesis_update"]
    base_status, base_score = replay(ups)
    base = top_cause(base_status, base_score)
    out = []
    for t in TABLES:
        st, sc = replay(ups, drop=t)
        top = top_cause(st, sc)
        changed = {h: [base_status[h], st[h]] for h in st if st[h] != base_status[h]}
        out.append({"drop_source": t, "top_cause": top, "conclusion_changes": top != base, "status_changes": changed})
    return {"top_cause": base, "by_source": out, "method": "deterministic replay of recorded outcomes without one source table"}


def run_question(qid: str, db, run_id: str, log_dir: Path | None = None) -> dict:
    log_dir = log_dir or ROOT / "logs"
    q = QUESTIONS[qid]
    tr = Tracer(run_id, log_dir)
    tr.log("orchestrator", "start", question_id=qid, question=q["title"], backend=badge(db),
           backend_name=getattr(db, "name", ""), provider="none ($0, deterministic SQL)", attribution=ATTRIBUTION)
    claims = []
    metric, treat, ctrl = q["kpi"]
    v, ids = _q(db, tr, metric, treat, "kpi")
    claims.append(_claim("kpi_period", metric, treat, v, ids, "KPI in the period"))
    kpi = {"metric": metric, "period": round(v, 3)}
    if ctrl:
        cv, cids = _q(db, tr, metric, ctrl, "kpi")
        claims.append(_claim("kpi_baseline", metric, ctrl, cv, cids, "KPI in the baseline"))
        kpi["baseline"] = round(cv, 3)
    hyps = q["hypotheses"]
    tr.log("planner", "hypotheses", hypotheses=[h["id"] for h in hyps], rule={"support_ratio": SUPPORT_RATIO, "refute_ratio": REFUTE_RATIO},
           note="fixed prior order from app/olist/questions.py; no model call")
    status = {}
    for h in hyps:
        status[h["id"]] = "open"
        tr.log("planner", "hypothesis_update", hyp=h["id"], text=h["text"], before=None, after="open", evidence_id=None)
    findings = []
    for h in hyps:
        outs = []
        for t in h["tests"]:
            a, aid = _q(db, tr, t["metric"], t["treatment"], t["id"])
            b, bid = _q(db, tr, t["metric"], t["control"], t["id"])
            ratio = round(a / b, 4) if a is not None and b else None
            o = outcome(ratio)
            ho = FLIP[o] if h.get("invert") else o
            outs.append(ho)
            before, after = status[h["id"]], combine(outs)
            status[h["id"]] = after
            effect = (1 / ratio if h.get("invert") else ratio) if ratio else None
            tr.log("evaluator", "hypothesis_update", hyp=h["id"], before=before, after=after, evidence_id=t["id"],
                   treatment=a, control=b, ratio=ratio, comparison_outcome=o, hyp_outcome=ho, effect=effect,
                   sources=spec(t["metric"], t["treatment"])["sources"])
            for suf, val, ids_, side in (("t", a, aid, "treatment"), ("c", b, bid, "control")):
                if val is not None:  # no rows -> no claim (nothing to verify); outcome is inconclusive
                    claims.append(_claim(f"{t['id']}_{suf}", t["metric"], t[side], val, ids_, f"{t['label']} ({side})"))
            findings.append({"hyp": h["id"], "evidence_id": t["id"], "label": t["label"],
                             "treatment": None if a is None else round(a, 3), "control": None if b is None else round(b, 3),
                             "ratio": ratio, "outcome": ho})
    wd, sens = why_diff(tr.path), sensitivity(tr.path)
    tr.log("analyst", "ranked", top_cause=wd["final_top"], status=status)
    out = {"run_id": run_id, "question_id": qid, "question": {"title": q["title"], "dataset": "olist"}, "kpi": kpi,
           "status": status, "top_cause": wd["final_top"], "findings": findings, "claims": claims,
           "why_diff": wd, "sensitivity": sens, "backend": badge(db), "attribution": ATTRIBUTION,
           "hyp_text": {h["id"]: h["text"] for h in hyps}}
    tr.log("writer", "memo", claims=len(claims))
    ts = [json.loads(l)["ts"] for l in tr.path.read_text(encoding="utf-8").splitlines()]
    out["system_seconds"] = round(ts[-1] - ts[0], 3)
    tr.log("orchestrator", "done", system_seconds_so_far=out["system_seconds"], measured_from="trace ts")
    (log_dir / f"result-{run_id}.json").write_text(json.dumps(out, indent=1, default=str))
    return out


def render_memo(r: dict, receipts: dict | None = None) -> str:
    rec = {x["claim_id"]: x for x in (receipts or {}).get("receipts", [])}
    k = r["kpi"]
    L = [f"# {r['question']['title']}", "", f"_Run `{r['run_id']}` · backend **{r['backend']}** · $0 (no model calls)_", "",
         f"> {r['attribution']}", "",
         f"**KPI** `{k['metric']}`: period {k['period']}" + (f" vs baseline {k['baseline']}" if "baseline" in k else ""), "",
         f"**Top supported cause:** {r['top_cause'] or 'none supported'}" + (f" — {r['hyp_text'][r['top_cause']]}" if r["top_cause"] else ""), "",
         "## Hypotheses", "", "| hypothesis | evidence | treatment | control | ratio | outcome |", "|---|---|---|---|---|---|"]
    for f in r["findings"]:
        L.append(f"| {f['hyp']} | {f['label']} | {f['treatment']} | {f['control']} | {f['ratio']} | {f['outcome']} |")
    L += ["", "## Why-diff (from hypothesis_update trace events)", ""]
    for h in r["why_diff"]["hypotheses"]:
        L.append(f"- {h['hyp']} (prior #{h['prior_rank']}): open -> **{h['after']}** by {', '.join(h['moved_by']) or 'no evidence'}")
    L += [f"- Prior first: {r['why_diff']['prior_first']}; final top: {r['why_diff']['final_top']}", "",
          "## Sensitivity of the conclusion (deterministic, drop one source)", ""]
    for s in r["sensitivity"]["by_source"]:
        L.append(f"- without `{s['drop_source']}`: top cause {s['top_cause']}" + (" **(changes)**" if s["conclusion_changes"] else " (same)"))
    L += ["", "## Claims and receipts", "", "| claim | value | receipt | backend | db now |", "|---|---|---|---|---|"]
    for c in r["claims"]:
        x = rec.get(c["id"], {})
        L.append(f"| {c['id']} ({c['label']}) | {c['value']} | {x.get('status', 'not verified').upper()} | {x.get('backend', '-')} | "
                 f"{round(x['db_value'], 3) if x.get('db_value') is not None else '-'} |")
    L += ["", f"System time (trace, investigation): {r['system_seconds']} s" +
          (f"; verify: {receipts['elapsed_s']} s" if receipts and receipts.get("elapsed_s") is not None else ""),
          "", "No accuracy metric: Olist has no ground truth for these questions."]
    if str(r.get("question_id", "")).endswith("q3"):
        L += ["", "**Caveat:** these are associations, not causes. Groups overlap (multi-seller orders are also more often "
              "late), so a supported hypothesis means the low-review rate differs between groups, not that the factor causes it. "
              "Reviews are counted per review row (an order with several reviews counts several times)."]
    return "\n".join(L) + "\n"
