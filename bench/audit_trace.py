"""audit.json builder: one explainable per-case trace (docs/AUDIT_TRACE.md, docs/audit_trace.schema.json).

Builds traces from EXISTING result rows (bench/results/*.jsonl) plus the dataset (question, gold) and the
failure catalogue (failures_all.jsonl). It never calls a model and never invents data: anything the run did
not record is the literal string "not_logged". Values recomputed deterministically by this tool from logged
data (e.g. whether a quote is verbatim in the context) are labelled "recomputed_by_audit".

    python -m bench.audit_trace --results bench/results/tatqa-markov-sample.jsonl --config agent_mk \
        --id 8757782d-306d-4a0d-b22e-ab0f2b58171c --data data/bench --failures failures_all.jsonl --out x.json
"""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

NL = "not_logged"
SCHEMA_VERSION = "audit-trace/1"
PROMPT_CHARS = 2000
RUN_NAMES = {"nebius-lightning-dev-v2": "v2", "nebius-lightning-dev": "v1", "nebius-lightning-pilot": "v1-pilot",
             "nvidia-super-pilot": "super-pilot"}
TAT_PROMPT_REF = {"agent": "bench/tatqa.py:agent", "rag": "bench/tatqa.py:rag", "react": "bench/tatqa.py:react"}
SECRET_RE = re.compile(r"(nvapi-[A-Za-z0-9_\-]{10,}|(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,}|"
                       r"(?:api[_-]?key|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|"
                       r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,})", re.I)


# ---------------------------------------------------------------- helpers
def run_name(path: Path, bench: str) -> str:
    s = Path(path).stem
    s = s[len(bench) + 1:] if s.startswith(bench + "-") else s
    return RUN_NAMES.get(s, s)


def sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode()).hexdigest()[:16]


def prompt_block(text: str | None, ref: str) -> dict:
    if text is None:
        return {"prompt_hash": NL, "prompt": NL, "prompt_template_ref": ref}
    return {"prompt_hash": sha(text), "prompt": text[:PROMPT_CHARS], "prompt_chars": len(text), "prompt_template_ref": ref}


def step(type_: str, summary: str, *, inputs=None, outputs=None, decision=None, prompt=None, errors=None,
         retries=None, model=None) -> dict:
    s = {"type": type_, "summary": summary,
         "inputs": inputs if inputs is not None else NL,
         "outputs": outputs if outputs is not None else NL,
         "decision": decision,
         "model": model,
         "latency_s": NL, "tokens": NL, "cost_usd": NL,
         "errors": errors if errors is not None else [], "retries": retries if retries is not None else 0}
    s.update(prompt or {})
    return s


def mk_decision(d: dict) -> dict:
    return {"source": "markov_controller", "decision": d.get("decision"), "state": d.get("state"),
            "action": d.get("action"), "reason": d.get("reason"), "carryover": d.get("carryover")}


def policy_decision(out: dict, g: dict, last: bool) -> dict:
    """Plain agent / vr: named fixed-policy decision for a gate round (trace-fix 8). ACCEPT = gate passed;
    RETRY = rejected and another round follows; STOP = rejected at the round cap. Logged decisions win."""
    for d in (out.get("policy_decisions") or []):
        if (d.get("state") or {}).get("gate_round") == g.get("round"):
            return {"source": "fixed_policy", "decision": "gate", "state": d.get("state"), "action": d["action"], "reason": d["reason"]}
    act = "ACCEPT" if not g.get("reasons") else ("STOP" if last else "RETRY")
    return {"source": "fixed_policy", "decision": "gate", "state": {"gate_round": g.get("round")}, "action": act,
            "reason": {"ACCEPT": "gate passed", "RETRY": "agent retries once on any gate rejection", "STOP": "gate still failing at the round cap"}[act]}


VERIFIER_TAGS = ("verify", "verifier", "vr_verify", "v2_critic", "v2_adjudicate")
JUDGE_TAGS = ("judge", "faith")


def call_role(tag: str) -> str:
    t = (tag or "").replace("_json_retry", "")
    return "verifier" if t in VERIFIER_TAGS else "judge" if t in JUDGE_TAGS else "generator"


def models_from_calls(calls: list[dict]) -> list[dict]:
    """Roles per call tag (trace-fix 8: everything used to be labelled generator)."""
    agg = {}
    for c in calls:
        if c.get("cached"):
            continue
        prov, _, mid = str(c.get("model") or "not_logged:not_logged").partition(":")
        k = (call_role(c.get("tag")), mid, prov)
        agg[k] = agg.get(k, 0) + 1
    return [{"role": r, "model_id": m, "provider": p, "calls": n, "source": "meter.trace_calls (role by call tag)"} for (r, m, p), n in agg.items()]


def ib_split(item_id: str):
    p = Path(__file__).resolve().parent / "splits" / "insightbench_split.json"
    if not p.exists():
        return NL
    sp = json.loads(p.read_text())
    return "tune" if item_id in sp.get("tune", []) else "eval" if item_id in sp.get("eval", []) else NL


def confidence_block(out: dict, legacy: dict) -> dict:
    """trace-fix 8: formula id + inputs logged by the system, recomputed with the SAME function."""
    from .confidence import FORMULAS, recompute
    f = out.get("conf_formula")
    if f not in FORMULAS:
        return {**legacy, "formula_id": "legacy_unlogged"}
    inp = dict(out.get("conf_inputs") or {})
    val = recompute(f, inp)
    if inp.get("cmap") is not None:
        inp["cmap"] = {"isotonic_points": inp["cmap"], "fit_on": "TAT-QA train" if f == "cr_tat" else "InsightBench tune (30)"}
    logged = out.get("confidence_det", out.get("confidence"))
    return {"deterministic": logged, "model_self_reported": out.get("confidence", NL), "formula_id": f, "formula": FORMULAS[f][1],
            "inputs": inp, "recomputed": val, "matches_logged": val == logged, "recompute_check": "recomputed_by_audit with bench.confidence"}


def vr_steps(out: dict) -> list[dict]:
    """agent_vr: one verify_retry_attempt step per attempt with its verify score and ACCEPT/RETRY/STOP decision."""
    res = []
    decs = out.get("vr_decisions") or []
    for a in out.get("vr_attempts") or []:
        k = a.get("attempt")
        d = next((x for x in decs if (x.get("state") or {}).get("attempt") == k), None)
        res.append(step("verify_retry_attempt", f"Verify attempt {k}: score {a.get('score', NL)} (deterministic {a.get('det', NL)}, verifier {a.get('verifier', NL)})"
                        + (f" -> {d['action']}" if d else ""),
                        outputs={k2: a.get(k2, NL) for k2 in ("score", "det", "verifier", "det_notes", "feedback")},
                        decision={"source": "verify_retry", "decision": "verify", "state": d.get("state"), "action": d["action"], "reason": d["reason"]} if d else None,
                        retries=max(0, (k or 1) - 1)))
    return res


def meter_models(meter: dict | None, role: str) -> list[dict]:
    out = []
    for k, n in ((meter or {}).get("providers") or {}).items():
        prov, _, mid = k.partition(":")
        out.append({"role": role, "model_id": mid, "provider": prov, "calls": n, "source": "meter.providers"})
    return out


def totals(meter: dict | None) -> dict:
    m = meter or {}
    return {"calls": m.get("calls", NL), "prompt_tokens": m.get("prompt_tokens", NL),
            "completion_tokens": m.get("completion_tokens", NL), "model_seconds": m.get("model_seconds", NL),
            "cost_usd": m.get("nebius_usd", NL), "errors": m.get("errors", NL),
            "finish_reasons": m.get("finish_reasons", NL)}


def secret_scan(obj) -> dict:
    """Redacts anything that looks like a credential in-place and reports how many were found."""
    hits = 0

    def walk(x):
        nonlocal hits
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            new, n = SECRET_RE.subn("[REDACTED]", x)
            hits += n
            return new
        return x
    clean = walk(obj)
    return clean, {"checked": True, "patterns": "nvapi-/sk-/Bearer/api_key=/gh*_/JWT", "redactions": hits}


def load_failures(path: Path | None) -> dict:
    out = {}
    if path and Path(path).exists():
        for line in Path(path).read_text().splitlines():
            f = json.loads(line)
            out[(f["bench"], f["run"], f["config"], f["id"])] = f
    return out


def failure_block(f: dict | None) -> dict | None:
    if not f:
        return None
    keep = ["cause", "kind", "fail_on", "code", "confidence", "consenso", "super_cat", "super_why", "super_conf", "error"]
    return {k: f[k] for k in keep if k in f} | {"source": "failures_all.jsonl"}


# ---------------------------------------------------------------- TAT-QA
def tat_item(data: Path, uid: str) -> dict | None:
    for split in ("dev", "train"):
        p = data / "tatqa" / f"tatqa_dataset_{split}.json"
        if not p.exists():
            continue
        for doc in json.loads(p.read_text()):
            for q in doc["questions"]:
                if q["uid"] == uid:
                    return {"doc": doc, "q": q, "split": split}
    return None


def tat_trace(row: dict, run: str, data: Path, fail: dict | None) -> dict:
    from . import tatqa as TQ
    it = tat_item(data, row["id"])
    out, meter = row.get("output") or {}, row.get("meter") or {}
    q = it["q"] if it else {}
    ctx = TQ.context(it["doc"]) if it else None
    nctx = TQ._norm(ctx) if ctx else None
    raw = out.get("raw") or {}
    decisions = out.get("decisions")
    steps, evidence = [], []

    # evidence: the final round's quotes (earlier rounds' quotes are not stored)
    for i, e in enumerate(out.get("evidence") or [], 1):
        verb = (bool(TQ._norm(e)) and TQ._norm(e) in nctx) if nctx else NL
        evidence.append({"id": f"e{i}", "text": e, "source": "model quote from the TAT-QA document context (table row or paragraph)",
                         "query": q.get("question", NL), "verbatim_in_context": verb, "verbatim_check": "recomputed_by_audit"})

    dec_iter = list(decisions or [])
    route = next((d for d in dec_iter if d["decision"] == "route"), None)
    if decisions is None:
        steps.append(step("plan", "No controller in this config: fixed single evidence-step pipeline (no routing).",
                          outputs={"pipeline": TAT_PROMPT_REF.get(row["system"], row["system"])}))
    else:
        steps.append(step("route_decision", f"Controller routed the question to {route['action'] if route else NL}.",
                          inputs={"question": q.get("question", NL)}, outputs={"route": out.get("route", NL)},
                          decision=mk_decision(route) if route else None))
        if route and route["action"].startswith("NUMERIC"):
            steps.append(step("plan", "NUMERIC route: up to 3 calculator (calc) turns before the answer; their expressions and observations were not stored.",
                              outputs={"calc_history": out["calc_history"]} if out.get("calc_history") is not None else NL,
                          prompt=prompt_block(None, "bench/tatqa.py:agent_markov (tat_mk_calc)"),
                              model=(out.get("route") or {}).get("model") or row.get("model")))
    gates = out.get("gate") or []
    gdec = [d for d in dec_iter if d["decision"] == "gate"]
    for g in gates:
        r = g.get("round")
        last = r == gates[-1].get("round")
        steps.append(step("writer", f"Evidence step round {r}: model returned answer + scale + expression + quoted evidence"
                          + (" (this is the final round; its output is below)." if last else " (intermediate output not stored)."),
                          inputs={"context": "TAT-QA table + paragraphs", "question": q.get("question", NL),
                                  "feedback": "previous round's gate reasons" if r else None},
                          outputs=({"raw_answer": raw.get("answer", NL), "raw_scale": raw.get("scale", NL),
                                    "expression": raw.get("expression", NL), "evidence_ids": [e["id"] for e in evidence],
                                    "self_confidence": out.get("confidence", NL)} if last else g.get("out", NL)),
                          prompt=prompt_block(None, "bench/tatqa.py:" + ("agent_markov" if decisions is not None else row["system"])),
                          model=row.get("model")))
        d = next((x for x in gdec if (x.get("state") or {}).get("gate_round") == r), None)
        verdict = "PASS" if not g.get("reasons") else "REJECT"
        steps.append(step("claim_gate", f"Claim Gate round {r}: {verdict}" + (": " + "; ".join(g["reasons"]) if g.get("reasons") else ""),
                          outputs={"verdict": verdict, "reasons": g.get("reasons", [])},
                          decision=mk_decision(d) if d else (policy_decision(out, g, last) if decisions is None else None),
                          retries=r))
    if raw:
        changes = []
        for k in ("answer", "scale"):
            if raw.get(k) != out.get(k):
                changes.append({"field": k, "before": raw.get(k), "after": out.get(k),
                                "rule": "tat_post.infer_scale" if k == "scale" else "tat_post.fmt_number/flatten"})
        steps.append(step("post_format", "Deterministic scale/format post-step (no model, gold never read): "
                          + ("; ".join(f"{c['field']} {c['before']!r} -> {c['after']!r}" for c in changes) if changes else "no change."),
                          inputs={"answer": raw.get("answer"), "scale": raw.get("scale"), "expression": raw.get("expression")},
                          outputs={"answer": out.get("answer"), "scale": out.get("scale"), "changes": changes}))
    ws = [s for s in steps if s["type"] == "writer"]
    if meter.get("calls") == 1 and len(ws) == 1 and not (route and route["action"].startswith("NUMERIC")):
        ws[0].update({"latency_s": meter.get("model_seconds", NL), "cost_usd": meter.get("nebius_usd", NL),
                      "tokens": {"prompt": meter.get("prompt_tokens"), "completion": meter.get("completion_tokens")},
                      "attribution": "item made exactly one model call, so item meter == this step"})
    sc = row.get("scores") or {}
    steps.append(step("scoring", f"Official TAT-QA scorer: EM={sc.get('em', NL)} F1={sc.get('f1', NL)} (raw answer before post-step: EM={sc.get('em_raw', NL)}).",
                      inputs={"uses_gold": True, "note": "only the scorer sees eval_only.gold"}, outputs=sc))

    gate_passed = out.get("gate_passed", NL)
    claims = [{"id": "c1", "text": f"answer = {out.get('answer')!r} (scale {out.get('scale')!r})", "cited_evidence": [e["id"] for e in evidence],
               "traceable": sc.get("traceable", NL), "gate_verdict": ("PASS" if gate_passed else "REJECT") if gate_passed != NL else NL,
               "why": "; ".join((gates[-1].get("reasons") if gates else []) or []) or ("all gate checks passed" if gate_passed is True else NL)}]
    n_g = len(gates)
    det = out.get("confidence_det", NL)
    base = (0.8 if n_g == 1 else 0.55) if gate_passed is True else 0.2
    conf = {"deterministic": det, "model_self_reported": out.get("confidence", NL),
            "formula": "0.8 if gate passed in round 0; 0.55 if passed after a retry; 0.2 if gate failed; capped at 0.1 if answer not traceable; capped at 0.4 if reranker relevance < RELEVANCE_MIN",
            "inputs": {"gate_passed": gate_passed, "gate_rounds": n_g, "traceable": sc.get("traceable", NL), "rerank_p": out.get("rerank_p", NL)},
            "recomputed_base": base if gate_passed != NL else NL}
    final = {"answer": out.get("answer", NL), "scale": out.get("scale", NL), "expression": out.get("expression", NL),
             "composed_from": {"claims": ["c1"], "evidence": [e["id"] for e in evidence]},
             "post_format": next((s["outputs"]["changes"] for s in steps if s["type"] == "post_format"), NL)}
    return {"case": {"bench": "tatqa", "run": run, "config": row["system"], "item_id": row["id"],
                     "question": q.get("question", NL), "dataset_split": it["split"] if it else NL, "ts": row.get("ts", NL),
                     "eval_only": {"_label": "EVAL ONLY - never shown to any model; used by the scorer and this audit",
                                   "gold": row.get("gold") or {"answer": q.get("answer", NL), "scale": q.get("scale", NL)},
                                   "derivation": q.get("derivation", NL)}},
            "steps": steps, "evidence": evidence, "claims": claims, "final_answer": final, "confidence": conf,
            "scores": {**sc, "explain": row.get("explain", NL), "failure": failure_block(fail)}}


# ---------------------------------------------------------------- InsightBench
def ib_trace(row: dict, run: str, data: Path, fail: dict | None) -> dict:
    p = data / "insightbench" / "data" / "notebooks" / f"{row['id']}.json"
    task = json.loads(p.read_text()) if p.exists() else {}
    out = row.get("output") or {}
    store = out.get("evidence_store") or {}
    decisions = out.get("decisions")
    steps, evidence = [], []
    dec = list(decisions or [])
    for d in [x for x in dec if x["decision"] == "depth"]:
        steps.append(step("route_decision", f"Controller set analysis depth {d['action']}.", decision=mk_decision(d)))
    steps.append(step("plan", "Planner decomposed the goal into analysis questions with one DuckDB SQL each (plan text not stored).",
                      inputs={"goal": (task.get("metadata") or {}).get("goal", NL)},
                      outputs={"queries_executed_total": out.get("queries", NL)},
                      prompt=prompt_block(None, "bench/insightbench.py:" + ("agent_markov" if decisions is not None else row["system"]) + " (plan)"),
                      model=row.get("model")))
    for qid, res in store.items():
        err = res.startswith("ERROR")
        ql = (out.get("queries_log") or {}).get(qid) or {}
        evidence.append({"id": qid, "source": "DuckDB query result", "query": ql.get("sql", NL), "analysis_question": ql.get("question", NL), "result": res[:600],
                         "result_truncated": len(res) > 600, "is_error": err})
        steps.append(step("sql", f"{qid}: " + (res.splitlines()[0][:160] if err else f"{len(res.splitlines()) - 1} result rows"),
                          inputs={"sql": ql.get("sql", NL), "question": ql.get("question", NL)}, outputs={"evidence_id": qid, "error": err},
                          errors=[x for x in ([ql["first_error"][:300]] if ql.get("first_error") else []) + ([res[:300]] if err else [])],
                          retries=1 if ql.get("first_error") else 0))
    rq = [x for x in dec if x["decision"] in ("requery", "sql_repair")]
    for d in rq:
        steps.append(step("evidence_eval" if d["decision"] == "requery" else "requery",
                          f"Controller {d['decision']}={d['action']}: {d['reason']}", decision=mk_decision(d)))
    if decisions is None:
        steps.append(step("evidence_eval", "Evidence Evaluator (LLM) decided sufficiency / follow-up queries between rounds; its replies were not stored.",
                          prompt=prompt_block(None, "bench/insightbench.py:agent (evaluate)")))
    rw = [x for x in dec if x["decision"] == "rewrite"]
    for g in out.get("gate") or []:
        r = g.get("round")
        steps.append(step("writer", f"Writer round {r}: produced {g.get('insights', NL)} insights + summary" + ("." if g.get("drafts") else " (draft text not stored)."),
                          outputs={"drafts": g["drafts"]} if g.get("drafts") else NL,
                          prompt=prompt_block(None, "bench/insightbench.py:write"), model=row.get("model")))
        d = next((x for x in rw if (x.get("state") or {}).get("gate_round") == r), None)
        steps.append(step("claim_gate", f"Claim Gate round {r}: {g.get('failed', NL)} of {g.get('insights', NL)} insights had numbers not in the cited results"
                          + (f"; summary numbers unsupported: {g['summary_unsupported']}" if g.get("summary_unsupported") else "")
                          + (f" ({g['note']})" if g.get("note") else ""),
                          outputs=g, decision=mk_decision(d) if d else None, retries=r or 0))
    for d in [x for x in dec if x["decision"] == "citation_check"]:
        steps.append(step("evidence_eval", f"Reranker citation check {d['action']}: {d['reason']}", decision=mk_decision(d)))
    sc = row.get("scores") or {}
    steps.append(step("scoring", f"ROUGE-1 insight={sc.get('insight_rouge1', NL)} summary={sc.get('summary_rouge1', NL)}; LLM judge={sc.get('summary_judge', NL)}.",
                      inputs={"uses_gold": True}, outputs=sc, model=row.get("judge_model") or NL))
    claims = []
    for i, c in enumerate(out.get("claims") or [], 1):
        ok = [e for e in c.get("evidence") or [] if e in store and not store[e].startswith("ERROR")]
        claims.append({"id": f"c{i}", "text": c["text"], "cited_evidence": c.get("evidence") or [],
                       "traceable": bool(ok) and len(ok) == len(c.get("evidence") or []),
                       "traceable_check": "recomputed_by_audit: every cited id exists and is not an SQL error",
                       "gate_verdict": "KEPT", "why": "every number is present in or recomputable from the cited results"})
    for j, c in enumerate(out.get("dropped_claims") or [], 1):
        claims.append({"id": f"d{j}", "text": c["text"], "cited_evidence": c.get("evidence") or [], "traceable": False,
                       "gate_verdict": "DROPPED", "why": f"{c.get('reason', NL)}; unsupported numbers: {c.get('unsupported', NL)}"})
    kept = [c for c in claims if c["gate_verdict"] == "KEPT"]
    final = {"insights": out.get("insights", NL), "summary": out.get("summary", NL),
             "composed_from": {"claims": [c["id"] for c in kept], "evidence": sorted({e for c in kept for e in c["cited_evidence"]}, key=lambda s: (len(s), s))},
             "post_format": [{"rule": "claim gate drop", "before": f"{len(claims)} insights", "after": f"{len(kept)} insights"}] if len(kept) != len(claims) else []}
    n_err = sum(v.startswith("ERROR") for v in store.values())
    conf = {"deterministic": out.get("confidence_det", NL), "model_self_reported": out.get("confidence", NL),
            "formula": "0.1 if no results or no kept claims; else min(0.9, 0.2 + 0.7 * share_sql_ok * share_claims_kept)",
            "inputs": {"queries": len(store), "sql_errors": n_err, "kept": len(kept), "dropped": len(claims) - len(kept),
                       "note": "evidence_store is the stored (possibly truncated) results; the live run used the same ids"},
            "recomputed": round(min(0.9, 0.2 + 0.7 * (1 - n_err / len(store)) * (len(kept) / len(claims))), 3) if store and kept else 0.1}
    md = task.get("metadata") or {}
    return {"case": {"bench": "insightbench", "run": run, "config": row["system"], "item_id": row["id"],
                     "question": md.get("goal", NL), "dataset_split": ib_split(row["id"]), "ts": row.get("ts", NL),
                     "eval_only": {"_label": "EVAL ONLY - never shown to any model; used by the scorer and this audit",
                                   "gold": {"insights": task.get("insights", NL), "summary": task.get("summary", NL)}}},
            "steps": steps, "evidence": evidence, "claims": claims, "final_answer": final, "confidence": conf,
            "scores": {**sc, "explain": row.get("explain", NL), "failure": failure_block(fail)}}


# ---------------------------------------------------------------- narrative + assembly
def narrative(t: dict) -> str:
    c, st = t["case"], t["steps"]
    parts = []
    r = next((s for s in st if s["type"] == "route_decision"), None)
    if r and r.get("decision"):
        parts.append(f"The controller chose {r['decision']['action']} because {r['decision']['reason']}.")
    elif c["bench"] == "tatqa":
        parts.append("No controller: the fixed pipeline answered in one evidence step.")
    if c["bench"] == "insightbench":
        sq = [s for s in st if s["type"] == "sql"]
        bad = [s for s in sq if s["errors"]]
        parts.append(f"It ran {len(sq)} SQL queries; {len(bad)} returned errors.")
    gates = [s for s in st if s["type"] == "claim_gate"]
    if gates:
        parts.append(f"The Claim Gate ran {len(gates)} round(s); last: {gates[-1]['summary'].split(': ', 1)[-1][:160]}.")
    pf = next((s for s in st if s["type"] == "post_format"), None)
    if pf and pf["outputs"]["changes"]:
        parts.append("Post-format changed " + ", ".join(f"{x['field']} {x['before']!r}->{x['after']!r}" for x in pf["outputs"]["changes"]) + ".")
    fa, g = t["final_answer"], c["eval_only"]["gold"]
    if c["bench"] == "tatqa":
        parts.append(f"Final answer {fa['answer']!r} [{fa['scale']}] vs gold {g.get('answer')} [{g.get('scale')}]: EM={t['scores'].get('em', NL)}.")
    else:
        drop = sum(1 for x in t["claims"] if x["gate_verdict"] == "DROPPED")
        parts.append(f"{len(fa['composed_from']['claims'])} insights kept, {drop} dropped by the gate; judge={t['scores'].get('summary_judge', NL)}, ROUGE-1={t['scores'].get('insight_rouge1', NL)}.")
    f = t["scores"].get("failure")
    parts.append(f"Failure cause: {f['cause']} ({f.get('code', '')[:140]})." if f else "No failure recorded for this case.")
    parts.append(f"Deterministic confidence {t['confidence']['deterministic']}.")
    return " ".join(parts)


def availability(t: dict) -> dict:
    def has(v):
        return v != NL and v is not None
    st = t["steps"]
    return {"steps.decision": any(s.get("decision") for s in st),
            "steps.prompt": any(has(s.get("prompt")) for s in st), "steps.latency_tokens_cost": any(has(s.get("latency_s")) for s in st),
            "steps.outputs": any(has(s.get("outputs")) for s in st), "evidence.query": any(has(e.get("query")) for e in t["evidence"]),
            "case_totals": has(t["totals"].get("calls"))}


CALL_STEP = {"plan": "plan", "tat_mk_calc": "plan", "evaluate": "evidence_eval", "sqlfix": "requery",
             "write": "writer", "tat_agent": "writer", "tat_rag": "writer", "rag": "writer", "react_final": "writer",
             "tat_react_final": "writer", "judge": "scoring", "faith": "scoring"}


def attach_calls(steps: list[dict], calls: list[dict]) -> list[dict]:
    """New runs (hook patch): per-call records from Meter.calls_log fill prompt/latency/tokens/cost of the matching
    step, in order. Unmatched calls are returned and kept in trace.llm_calls (nothing is dropped)."""
    left = []
    for c in calls:
        typ = CALL_STEP.get(c.get("tag", "").replace("_json_retry", ""))
        tgt = next((s for s in steps if s["type"] == typ and s.get("prompt_hash") in (None, NL)), None)
        if tgt is None:
            left.append(c)
            continue
        tgt.update({"prompt_hash": c.get("prompt_hash", NL), "prompt": c.get("prompt", NL), "prompt_chars": c.get("prompt_chars", NL),
                    "latency_s": c.get("latency_s", NL), "cost_usd": c.get("cost_usd", NL), "model": c.get("model") or tgt.get("model"),
                    "tokens": {"prompt": c.get("prompt_tokens"), "completion": c.get("completion_tokens")}, "reply_head": c.get("reply_head", NL)})
        if c.get("error"):
            tgt["errors"].append(c["error"])
    return left


def build(row: dict, results_path: Path, data: Path, failures: dict) -> dict:
    bench = row["bench"]
    run = run_name(results_path, bench)
    fail = failures.get((bench, run, row["system"], row["id"]))
    t = (tat_trace if bench == "tatqa" else ib_trace)(row, run, data, fail)
    calls0 = (row.get("meter") or {}).get("trace_calls")
    out0 = row.get("output") or {}
    models = (models_from_calls(calls0) if calls0 else meter_models(row.get("meter"), "generator")) + meter_models(row.get("judge_meter"), "judge")
    sc0 = row.get("scores") or {}
    if not any(m["role"] == "judge" for m in models) and (sc0.get("summary_judge") is not None or sc0.get("judge") is not None):
        from .llmio import JUDGE_MODEL
        models.append({"role": "judge", "model_id": JUDGE_MODEL, "provider": "nebius", "calls": NL, "source": "scores present; judge meter not stored (model = JUDGE_MODEL)"})
    if out0.get("vr_attempts"):
        t["steps"][-1:-1] = vr_steps(out0)  # before scoring
    t["confidence"] = confidence_block(out0, t["confidence"])
    if t["scores"].get("failure") is None:  # trace-fix 8: failure was null whenever no failures file was passed
        t["scores"]["failure"] = {"cause": failure_cause(row), "source": "bench.audit_trace.failure_cause (deterministic, gold-aware, index only)"}
    if not models and row.get("model"):
        models.append({"role": "generator", "model_id": row["model"], "provider": row.get("provider"), "calls": NL, "source": "row.model"})
    if row["system"].endswith("nv"):
        models.append({"role": "classifier", "model_id": "nvidia/prompt-task-and-complexity-classifier", "provider": "local (CPU, open weights; features precomputed)",
                       "calls": NL, "source": "bench/features/nvclf-*.json"})
    if row["system"].endswith("mkr"):
        models.append({"role": "reranker", "model_id": "nvidia/llama-nemotron-rerank-vl-1b-v2", "provider": "build.nvidia.com",
                       "calls": len((row.get("output") or {}).get("rerank_p") or []) or NL, "source": "output.rerank_p"})
    calls = (row.get("meter") or {}).get("trace_calls")
    t["llm_calls"] = attach_calls(t["steps"], calls) if calls else NL
    if t["case"]["question"] == NL and row.get("question"):
        t["case"]["question"] = row["question"]
    t["case"]["code_rev"] = row.get("code_rev", NL)
    if row.get("error"):
        t["steps"].append(step("scoring", "Run error: " + row["error"][:200], errors=[row["error"][:300]]))
    t = {"schema_version": SCHEMA_VERSION, **t, "models": models, "totals": {"system": totals(row.get("meter")), "judge": totals(row.get("judge_meter"))},
         "source": {"results_file": str(results_path), "row_key": [row["bench"], row["system"], row["id"]]}}
    t["narrative"] = narrative(t)
    t["availability"] = availability(t)
    t, scan = secret_scan(t)
    t["secret_scan"] = scan
    return t


def find_row(path: Path, config: str, item: str) -> dict:
    for line in Path(path).read_text().splitlines():
        r = json.loads(line)
        if r["system"] == config and r["id"] == item:
            return r
    raise KeyError(f"{config}/{item} not in {path}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--data", default="data/bench")
    ap.add_argument("--failures")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    t = build(find_row(Path(a.results), a.config, a.id), Path(a.results), Path(a.data), load_failures(a.failures))
    s = json.dumps(t, indent=2, ensure_ascii=False, default=str)
    Path(a.out).write_text(s) if a.out else print(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------- per-item traces written by bench/run.py
def failure_cause(row: dict) -> str:
    """Deterministic, gold-aware label for the index only (never fed back to any system)."""
    if row.get("error"):
        return "run_error: " + row["error"].split(":")[0]
    sc, o = row.get("scores") or {}, row.get("output") or {}
    if row["bench"] == "tatqa":
        if sc.get("em") == 1:
            return "correct"
        if sc.get("em_raw") == 1 or (str(o.get("answer")) == str((row.get("gold") or {}).get("answer")) and o.get("scale") != (row.get("gold") or {}).get("scale")):
            return "scale"
        if not o.get("gate_passed", True):
            return "gate_failed"
        if not sc.get("traceable", True):
            return "untraceable_number"
        return "wrong_answer" if (sc.get("f1") or 0) == 0 else "partial_answer"
    if sc.get("excluded"):
        return "excluded"
    if o.get("sql_errors"):
        return "sql_error" if (sc.get("summary_judge") or 0) < 0.6 else "ok_with_sql_errors"
    j = sc.get("summary_judge")
    return "judge_none" if j is None else ("ok" if j >= 0.6 else "weak_insight")


def _disk_free_gb(p: Path) -> float:
    import shutil
    return shutil.disk_usage(p).free / 1e9


def write_item_trace(row: dict, results_path: Path, data: Path, root: Path, min_free_gb: float = 2.0) -> dict:
    """bench/results/traces/<run>/<config>/<item_id>.audit.json + one line in <root>/<run>/audit_index.jsonl.
    Prompts in the trace are truncated (AUDIT_PROMPT_CHARS, default 2000); the full prompt texts go to a gzip
    sidecar <item_id>.prompts.json.gz only if more than min_free_gb of disk is free."""
    import gzip
    row = dict(row)
    meter = dict(row.get("meter") or {})
    calls = meter.get("trace_calls") or []
    full = [{"i": c.get("i"), "tag": c.get("tag"), "prompt": c.pop("prompt_full", None)} for c in calls]
    row["meter"] = meter
    run = Path(results_path).stem
    d = root / run / row["system"]
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(row["id"]))
    t = build(row, Path(results_path), data, {})
    if isinstance(row.get("output"), dict) and row["output"].get("v71"):  # V7.1: every gate decision with its reason
        t["v71"] = row["output"]["v71"]
    p = d / f"{safe}.audit.json"
    p.write_text(json.dumps(t, indent=1, ensure_ascii=False, default=str))
    gz = None
    if any(f["prompt"] for f in full) and _disk_free_gb(root) > min_free_gb:
        clean, _ = secret_scan(full)
        gz = d / f"{safe}.prompts.json.gz"
        with gzip.open(gz, "wt") as f:
            json.dump(clean, f, ensure_ascii=False)
    sc = row.get("scores") or {}
    idx = {"id": row["id"], "config": row["system"], "bench": row["bench"],
           "score": sc.get("em") if row["bench"] == "tatqa" else sc.get("summary_judge"),
           "failure_cause": failure_cause(row), "path": str(p), "prompts_gz": str(gz) if gz else None,
           "redactions": t["secret_scan"]["redactions"]}
    with (root / run / "audit_index.jsonl").open("a") as f:
        f.write(json.dumps(idx) + "\n")
    return idx


def backfill(results_path: Path, data: Path, root: Path) -> int:
    """Write traces for every row of an existing results JSONL (rows from before the hook was wired)."""
    n = 0
    seen = {}
    for line in Path(results_path).read_text().splitlines():
        r = json.loads(line)
        seen[(r["system"], r["id"])] = r  # last record wins (resume)
    for r in seen.values():
        write_item_trace(r, Path(results_path), data, root)
        n += 1
    return n
