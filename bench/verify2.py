"""verify-v2: three verification strategies on top of the Markov controller (agent_mk), after verify-retry (agent_vr)
lost 27 TAT-QA items. Diagnosis (docs/VERIFY_V2.md): the Super verifier was over-confident (57 perfect scores, some on
wrong arithmetic) and agent_vr bypassed the traceability-check re-ask. Literature (Huang et al. 2023; Stechly et al. 2024)
says intrinsic LLM self-verification is unreliable; gains come from EXTERNAL signals (tools, execution, agreement).
So every config below keeps agent_mk unchanged (including its traceability-check re-ask) and only adds a signal on top:

  *_pot  (a) Program-of-Thought re-execution (PoT/PAL + CRITIC tool idea). An INDEPENDENT call writes named operands
         copied from the context and a Python arithmetic expression; we execute it (safe_eval) and check every operand
         against the context. Agreement with the agent answer -> high confidence; disagreement -> ONE re-ask with
         both results, then the traceability check again. No LLM judge. Deterministic confidence.
  *_sc   (b) Self-consistency (Wang et al. 2023): agent_mk at T=0 + 2 samples at T=0.7; majority vote over the
         normalised (answer, scale); confidence = vote share (x gate). Only when all 3 disagree, ONE adjudication
         call picks a candidate (CRITIC-style, sees the tool results), never a free-form score.
  *_cr   (c) CRITIC-style critique (Gou et al. 2024): tool results (recomputed expression, gate reasons, operand
         check, traceability, PoT-free) are given to a Lightning critic that returns p_correct + critique; revise
         when p_correct < CR_THRESHOLD. The revision is ALWAYS computed and logged (offline replay), but only used
         below the threshold. CR_THRESHOLD and the confidence map are fitted on TAT-QA TRAIN only
         (scripts/v2_calibrate.py); dev is never used.
Everything is logged per item (v2 block) and lands in the auto audit.json trace.
"""
from __future__ import annotations
import contextlib, json, os, re
from .common import nums, supported, gate_claim, conf01

CR_THRESHOLD = float(os.environ.get("CR_THRESHOLD", "0.5"))
CR_CONF_MAP = json.loads(os.environ.get("CR_CONF_MAP", "null") or "null")  # [[p_hi, conf], ...] fitted on TRAIN
CR_ALWAYS_REVISE = os.environ.get("CR_ALWAYS_REVISE", "0") == "1"  # trace-fix 6: revise only when it can be used (was: always, for replay)
SC_SAMPLES, SC_TEMP = 2, 0.7


@contextlib.contextmanager
def sampling(t: float):
    from . import nebius
    old = nebius.TEMPERATURE
    nebius.TEMPERATURE = t
    try:
        yield
    finally:
        nebius.TEMPERATURE = old


def _num(x) -> float | None:
    v = nums(str(x))
    return v[0] if len(v) == 1 else None


def same_answer(a, b, sa="", sb="") -> bool:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) <= max(0.011, 0.005 * abs(nb)) and (sa or "") == (sb or "")
    return _key(a) == _key(b)


def _key(a) -> str:
    if isinstance(a, list):
        return "|".join(sorted(_key(x) for x in a))
    return re.sub(r"[\s$,.%]+", " ", str(a).lower()).strip()


# ============================================================ TAT-QA
def _revise(it, m, prev: dict, feedback: str) -> tuple[dict, list[dict]]:
    """One revision with feedback, then the SAME traceability check with its own re-ask (max 2 gate rounds, as agent)."""
    from .tatqa import ANS, QUOTE_RULE, context, gate
    ctx = context(it["doc"])
    msgs = [{"role": "system", "content": "You are VeriAgent Why's evidence step. Answer only from the context; quote your evidence. " + ANS + QUOTE_RULE},
            {"role": "user", "content": ctx + "\nQUESTION: " + it["q"]["question"]},
            {"role": "assistant", "content": json.dumps({k: prev.get(k) for k in ("answer", "scale", "expression", "evidence")})[:2000]},
            {"role": "user", "content": feedback + " Decide which is right from the context and answer again. " + ANS}]
    log = []
    for g in range(2):
        out = m.call_json(msgs, "v2_revise", "s2", 600)
        reasons = gate(out, ctx)
        log.append({"round": g, "reasons": reasons, "out": {k: out.get(k) for k in ("answer", "scale", "expression", "evidence")}})
        if not reasons:
            break
        msgs = msgs + [{"role": "assistant", "content": json.dumps(out)[:2000]},
                       {"role": "user", "content": "Traceability check rejected: " + "; ".join(reasons) + ". Fix and answer again. " + ANS + QUOTE_RULE}]
    return out, log


def tools(it, base: dict) -> dict:
    """CRITIC 'tool' outputs: pure functions of the answer and the context (no gold)."""
    from .tatqa import context, gate, safe_eval, traceable
    ctx = context(it["doc"])
    raw = base.get("raw") or {}
    expr = str(raw.get("expression") or "")
    val = None
    if expr:
        try:
            val = round(safe_eval(expr), 4)
        except Exception as e:
            val = f"error {type(e).__name__}"
    ev = " ".join(base.get("evidence") or [])
    ops_in_ev = [v for v in nums(expr) if v not in (100, 1000) and not supported(abs(v), [abs(x) for x in nums(ev)], True)] if expr else []
    return {"expression": expr, "expression_value": val, "gate_reasons": gate({**raw, "evidence": base.get("evidence")}, ctx),
            "operands_not_in_cited_evidence": ops_in_ev, "answer_traceable_to_context": traceable(str(base.get("answer")), ctx)}


POT_SYS = ("You are a careful financial analyst who answers by writing a tiny program. Copy every operand you need verbatim "
           "from the context, then give ONE Python arithmetic expression over those names. Reply with JSON only: "
           "{\"values\": {\"name\": number copied from the context}, \"expression\": \"arithmetic over the names\", "
           "\"scale\": one of [\"\", \"thousand\", \"million\", \"billion\", \"percent\"], \"is_arithmetic\": true|false}. "
           "Percentage change = (new - old) / old * 100; keep the sign. If the question needs no arithmetic set is_arithmetic false.")


def pot(it, m) -> dict:
    """Independent program-of-thought answer, executed deterministically."""
    from .tatqa import context, safe_eval
    ctx = context(it["doc"])
    o = m.call_json([{"role": "system", "content": POT_SYS}, {"role": "user", "content": ctx + "\nQUESTION: " + it["q"]["question"]}], "v2_pot", "s2", 500)
    res = {"pot_raw": {k: o.get(k) for k in ("values", "expression", "scale", "is_arithmetic")}, "pot_value": None, "pot_ok": False}
    vals = o.get("values") if isinstance(o.get("values"), dict) else {}
    if not o.get("is_arithmetic") or not vals:
        return res
    cn = [abs(x) for x in nums(ctx)]
    missing = [k for k, v in vals.items() if _num(v) is None or not supported(abs(_num(v)), cn, True)]
    expr = str(o.get("expression") or "")
    for k in sorted(vals, key=len, reverse=True):
        if _num(vals[k]) is not None:
            expr = re.sub(r"\b" + re.escape(str(k)) + r"\b", f"({_num(vals[k])})", expr)
    try:
        v = round(safe_eval(expr), 2)
    except Exception as e:
        res["pot_error"] = f"{type(e).__name__}"
        return res
    res.update({"pot_value": v, "pot_expr_resolved": expr, "pot_missing_operands": missing, "pot_ok": not missing,
                "pot_scale": o.get("scale") if o.get("scale") in ("", "thousand", "million", "billion", "percent") else ""})
    return res


def tat_pot(it, m) -> dict:
    from .tatqa import agent_markov
    base = agent_markov(it, m, False)
    p = pot(it, m)
    v2 = {"strategy": "pot", **p, "base_answer": base["answer"], "base_scale": base.get("scale")}
    det = base["confidence_det"]
    if not p["pot_ok"]:
        v2["decision"] = "NO_SIGNAL (non-arithmetic or PoT operands not in context): keep agent_mk answer and confidence"
        return {**base, "v2": v2}
    if same_answer(base["answer"], p["pot_value"]) or same_answer(base["answer"], round(p["pot_value"], 2)):
        v2["decision"] = "AGREE: independent executed program reproduces the answer"
        return {**base, "confidence": min(0.95, det + 0.15) if base["gate_passed"] else det, "confidence_det": min(0.95, det + 0.15) if base["gate_passed"] else det, "v2": v2}
    fb = (f"An independent recomputation from context values {json.dumps(p['pot_raw'].get('values'))[:400]} with "
          f"{p['pot_raw'].get('expression')} gives {p['pot_value']}, but you answered "
          f"{base['answer']}. Check the operands, the formula and the sign. Keep the scale exactly as the context states it.")
    out, log = _revise(it, m, {**(base.get("raw") or {}), "evidence": base.get("evidence")}, fb)
    from .tatqa import _pred
    from . import fixes as FX
    r = _pred(out, it)
    from .tatqa import context as _c
    g = FX.revision_guard(base, r, it, _c(it["doc"]))
    if g:
        v2.update({"decision": f"DISAGREE -> revision rejected ({g})"})
        return {**base, "v2": v2}
    agree = same_answer(r["answer"], p["pot_value"])
    passed = not log[-1]["reasons"]
    v2.update({"decision": "DISAGREE -> revised once" + (", revision agrees with PoT" if agree else ", still disagrees"), "revision_gate": log})
    conf = (0.75 if agree else 0.35) if passed else 0.15
    return {**base, **r, "gate_passed": passed, "confidence": conf, "confidence_det": conf, "v2": v2}


def tat_sc(it, m) -> dict:
    from .tatqa import agent_markov
    cands = [agent_markov(it, m, False)]
    for _ in range(SC_SAMPLES):
        with sampling(SC_TEMP):
            cands.append(agent_markov(it, m, False))
    groups: list[list[int]] = []
    for i, c in enumerate(cands):
        for g in groups:
            if same_answer(c["answer"], cands[g[0]]["answer"], c.get("scale"), cands[g[0]].get("scale")):
                g.append(i); break
        else:
            groups.append([i])
    # rank: votes, then gate-passed votes, then earliest (the T=0 answer wins ties)
    groups.sort(key=lambda g: (-len(g), -sum(cands[i]["gate_passed"] for i in g), g[0]))
    best = groups[0]
    v2 = {"strategy": "self_consistency", "samples": [{"answer": c["answer"], "scale": c.get("scale"), "gate_passed": c["gate_passed"]} for c in cands],
          "groups": groups, "temperature": SC_TEMP}
    if len(best) == 1:  # full disagreement: one adjudication call with tool results, picks an index only
        from .tatqa import context
        T = [tools(it, c) for c in cands]
        o = m.call_json([{"role": "system", "content": "Three candidate answers to the same question disagree. Using the context and the tool results "
                          "(recomputed expressions, traceability-check reasons), pick the candidate that is exactly right. Reply with JSON only: {\"pick\": 0|1|2, \"why\": str}."},
                         {"role": "user", "content": context(it["doc"]) + "\nQUESTION: " + it["q"]["question"] + "\nCANDIDATES: "
                          + json.dumps([{"i": i, "answer": c["answer"], "scale": c.get("scale"), "tools": T[i]} for i, c in enumerate(cands)], default=str)[:5000]}],
                        "v2_adjudicate", "s2", 300)
        k = o.get("pick") if o.get("pick") in (0, 1, 2) else 0
        v2.update({"decision": f"NO_MAJORITY -> adjudicated pick {k}", "adjudication": o})
        c = cands[k]
        conf = 0.3 if c["gate_passed"] else 0.15
    else:
        c = cands[best[0]]
        share = len(best) / len(cands)
        v2["decision"] = f"MAJORITY {len(best)}/{len(cands)}"
        conf = round((0.4 + 0.5 * share) if c["gate_passed"] else 0.2 * share + 0.05, 3)
    return {**c, "confidence": conf, "confidence_det": conf, "v2": v2}


CRIT_SYS = ("You are a critic with tool access results. Check the candidate answer against the context: right rows/columns and "
            "year, right formula and sign, right scale; for text answers the COMPLETE span exactly as worded in the context (never ask to shorten or trim a correct span; do not change the scale of a value the context states with a scale). Use the TOOL RESULTS (recomputed "
            "expression value, traceability-check reasons, operands missing from the cited evidence). Reply with JSON only: "
            "{\"p_correct\": probability 0-1 that the answer is exactly right, \"critique\": \"concrete problem to fix, or empty\"}.")


def cr_conf(p: float | None, passed: bool) -> float:
    from .confidence import cr_tat, load_map
    return cr_tat(p, passed, False, CR_CONF_MAP or load_map("tatqa"))


def tat_cr(it, m) -> dict:
    from .tatqa import agent_markov, context, _pred
    from . import fixes as FX
    from .confidence import load_map
    base = agent_markov(it, m, False)
    T = tools(it, base)
    o = m.call_json([{"role": "system", "content": CRIT_SYS},
                     {"role": "user", "content": context(it["doc"]) + "\nQUESTION: " + it["q"]["question"] + "\nCANDIDATE: "
                      + json.dumps({"answer": base["answer"], "scale": base.get("scale"), "evidence": base.get("evidence")})[:2000]
                      + "\nTOOL RESULTS: " + json.dumps(T, default=str)}], "v2_critic", "s2", 300)
    p0 = conf01(o.get("p_correct"))
    v2 = {"strategy": "critic", "tools": T, "critic": {"p_correct": p0, "critique": str(o.get("critique") or "")[:400]}, "threshold": CR_THRESHOLD}
    rev, guard = None, None
    want = p0 is not None and p0 < CR_THRESHOLD
    if str(o.get("critique") or "").strip() and (want or CR_ALWAYS_REVISE):
        out, log = _revise(it, m, {**(base.get("raw") or {}), "evidence": base.get("evidence")}, "A critic with tool results says: " + str(o.get("critique"))[:600])
        rev = {**_pred(out, it), "gate_passed": not log[-1]["reasons"]}
        v2["revision"] = {"answer": rev["answer"], "scale": rev.get("scale"), "gate_passed": rev["gate_passed"], "gate": log}
        # trace-fixes 1 + 7: never accept a truncation of the original span or a pure magnitude/scale rewrite
        from .tatqa import context as _c
        guard = FX.revision_guard(base, rev, it, _c(it["doc"]))
        v2["revision"]["guard"] = guard
    use = rev is not None and want and rev["gate_passed"] and not guard
    v2["decision"] = ("REVISED (p_correct < threshold, revision passed gate and guards)" if use
                      else f"KEPT agent_mk answer (revision rejected: {guard})" if guard and want else "KEPT agent_mk answer")
    fin = {**base, **rev} if use else base
    cmap = CR_CONF_MAP or load_map("tatqa")
    inputs = {"p_correct": p0, "gate_passed": fin["gate_passed"], "revised": bool(use), "cmap": cmap}
    from .confidence import cr_tat
    conf = cr_tat(**inputs)
    return {**fin, "confidence": conf, "confidence_det": conf, "v2": v2, "conf_formula": "cr_tat", "conf_inputs": inputs}


RULES = {"tat_pot": "AGREE -> min(0.95, tat_det+0.15) if gate passed; DISAGREE revised -> 0.75 agree / 0.35 not, 0.15 if gate failed",
         "tat_sc": "MAJORITY -> 0.4+0.5*share if gate passed else 0.2*share+0.05; NO_MAJORITY -> 0.3 / 0.15",
         "ib_sc": "min(0.9, 0.15 + 0.75 * mean insight agreement), 0.1 without insights"}


def declared(fn, rule_id):
    """trace-fix 8: when a config overrides the base confidence, log the config's declared rule (formula "fixed"),
    so the trace's formula always reproduces the logged value."""
    def run(*a, **k):
        from .confidence import recompute
        r = fn(*a, **k)
        if recompute(r.get("conf_formula"), r.get("conf_inputs")) != r.get("confidence"):
            r["conf_formula"], r["conf_inputs"] = "fixed", {"value": r.get("confidence"), "rule": RULES[rule_id] + " | " + str((r.get("v2") or {}).get("decision", ""))}
        return r
    run.__name__ = fn.__name__
    return run


TAT_SYSTEMS = {"agent_pot": declared(tat_pot, "tat_pot"), "agent_sc": declared(tat_sc, "tat_sc"), "agent_cr": tat_cr}


# ============================================================ InsightBench
def _ib_ctx(task, con, tables, base):
    from .insightbench import schema, _context, _fmt
    res = {k: {"question": q["question"], "sql": q["sql"], "result": base["evidence_store"].get(k, "")} for k, q in base["queries_log"].items()}
    return _context(task, schema(con, tables)) + "\nRESULTS\n" + _fmt(res), base["evidence_store"]


def _ib_gate(out, view):
    """Same deterministic gate as agent_mk (trace-fixes 2+3): empty/failed cited results are not sources and
    comparatives/superlatives are checked against the cited tables."""
    from .insightbench import norm_ids, gate_ib_claim
    ins = [i for i in (out.get("insights") or []) if isinstance(i, dict) and i.get("text")][:10]
    kept = []
    for i in ins:
        ev = norm_ids(i.get("evidence"), view)
        un, _, contra = gate_ib_claim({"text": i["text"], "evidence": ev}, view)
        if not un and not contra:
            kept.append({"text": i["text"], "evidence": ev})
    return kept, len(ins) - len(kept)


def ib_pv(task, con, tables, m):
    """(a) for InsightBench: the deterministic traceability check is the verifier; ALWAYS re-ask while claims fail
    (agent_vr's retried cases improved), max GATE_ROUNDS, no LLM score."""
    from .insightbench import agent_markov
    from .markov import Controller

    class AlwaysRewrite(Controller):
        def rewrite(self, n_ins, n_bad, summary_bad, round_, prev_bad, max_rounds):
            if (n_bad or summary_bad) and round_ < max_rounds and not (prev_bad is not None and n_bad > prev_bad):
                return self._d("rewrite", {"gate_round": round_, "insights": n_ins, "failed": n_bad, "summary_unsupported": summary_bad},
                               "REWRITE", "verify-v2 pv: deterministic gate failed, always re-ask") == "REWRITE"
            return super().rewrite(n_ins, n_bad, summary_bad, round_, prev_bad, max_rounds)
    r = agent_markov(task, con, tables, m, ctl=AlwaysRewrite(False, None, "insightbench"))
    return {**r, "v2": {"strategy": "pot_gate_always_reask"}}


def ib_sc(task, con, tables, m):
    """(b) self-consistency over Writer samples: each kept insight's agreement = share of 2 T=0.7 samples that contain a
    similar insight (ROUGE-1 >= 0.4); insights are re-ordered by agreement; zero-agreement insights dropped if >=3 remain."""
    from .insightbench import agent_markov, OUT_SPEC, rouge1
    base = agent_markov(task, con, tables, m)
    ctx, view = _ib_ctx(task, con, tables, base)
    samples = []
    for _ in range(SC_SAMPLES):
        with sampling(SC_TEMP):
            o = m.call_json([{"role": "system", "content": "You are the Writer of a root-cause analytics agent. " + OUT_SPEC},
                             {"role": "user", "content": ctx}], "v2_sc_write", "s2", 3500)
        samples.append(_ib_gate(o, view)[0])
    agr = [sum(any(rouge1(c["text"], s["text"]) >= 0.4 for s in smp) for smp in samples) / SC_SAMPLES for c in base["claims"]]
    order = sorted(range(len(agr)), key=lambda i: (-agr[i], i))
    keep = [i for i in order if agr[i] > 0] if sum(a > 0 for a in agr) >= 3 else order
    claims = [base["claims"][i] for i in keep]
    conf = round(min(0.9, 0.15 + 0.75 * (sum(agr) / len(agr))), 3) if agr else 0.1
    return {**base, "claims": claims, "insights": [c["text"] for c in claims], "confidence": conf, "confidence_det": conf,
            "v2": {"strategy": "self_consistency", "agreement": agr, "kept_order": keep, "sample_sizes": [len(s) for s in samples]}}


def ib_cr(task, con, tables, m):
    """(c) CRITIC: critic sees each kept insight with its cited results and the gate's number log; flagged insights
    trigger ONE rewrite, which goes through the same deterministic gate; flagged insights the rewrite did not fix are dropped
    only if >=3 insights remain."""
    from .insightbench import agent_markov, OUT_SPEC
    base = agent_markov(task, con, tables, m)
    ctx, view = _ib_ctx(task, con, tables, base)
    pk = [{"i": i, "text": c["text"], "cited": {e: view.get(e, "")[:700] for e in c["evidence"][:3]}} for i, c in enumerate(base["claims"])]
    o = m.call_json([{"role": "system", "content": "You are a critic of data-analysis insights. For each insight check, against ITS cited query results only, "
                      "that the numbers, direction and comparison are right and that it addresses the goal. Reply with JSON only: "
                      "{\"flags\": [{\"i\": index, \"problem\": str}], \"p_correct\": probability 0-1 that the main finding is right}."},
                     {"role": "user", "content": "GOAL: " + task["metadata"]["goal"] + "\nINSIGHTS: " + json.dumps(pk)[:9000]}], "v2_critic", "s2", 800)
    flags = [f for f in (o.get("flags") or []) if isinstance(f, dict) and isinstance(f.get("i"), int) and 0 <= f["i"] < len(base["claims"])]
    v2 = {"strategy": "critic", "flags": flags, "p_correct": conf01(o.get("p_correct"))}
    claims = base["claims"]
    if flags:
        w = m.call_json([{"role": "system", "content": "You are the Writer of a root-cause analytics agent. " + OUT_SPEC},
                         {"role": "user", "content": ctx}, {"role": "assistant", "content": json.dumps({"insights": base["claims"], "summary": base["summary"]})[:4000]},
                         {"role": "user", "content": "A critic flagged: " + json.dumps(flags)[:1500] + ". Fix those insights using the cited results; keep the others. " + OUT_SPEC}],
                        "v2_cr_write", "s2", 3500)
        kept, dropped = _ib_gate(w, view)
        v2["rewrite"] = {"kept": len(kept), "dropped_by_gate": dropped}
        if len(kept) >= max(3, len(claims) // 2):
            claims = kept
            base = {**base, "summary": w.get("summary") or base["summary"]}
    from .confidence import cr_ib, load_map
    inputs = {"p_correct": v2["p_correct"], "base_det": base["confidence_det"], "cmap": load_map("insightbench")}
    conf = cr_ib(**inputs)
    return {**base, "claims": claims, "insights": [c["text"] for c in claims], "confidence": conf, "confidence_det": conf, "v2": v2,
            "conf_formula": "cr_ib", "conf_inputs": inputs}


IB_SYSTEMS = {"agent_pot": ib_pv, "agent_sc": declared(ib_sc, "ib_sc"), "agent_cr": ib_cr}
