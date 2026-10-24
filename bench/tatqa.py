"""TAT-QA adapter (hybrid table + text financial QA) -> thin VeriAgent Why path.

- agent: Evidence step (model quotes the cells/sentences it uses and gives an arithmetic expression)
  -> deterministic Claim Gate: every quote must occur in the context, every number in the expression
  must be a context number, and eval(expression) must equal the answer. On failure, one feedback
  round (max 2 gate rounds); the final answer is then kept but counted as gate-failed.
- rag:   BM25 top paragraphs + full table, one answer call. No checks.
- react: ReAct with a calculator tool (up to 4 steps), then answer. No checks.
Scoring: official TAT-QA scorer (tatqa_metric.TaTQAEmAndF1, downloaded) + our 'unsupported-number
rate', applied identically to every system (see `traceable`).
"""
from __future__ import annotations
import ast, itertools, json, operator, re, sys, time
from pathlib import Path
from app.bm25 import bm25
from .common import nums, supported
from .llmio import Meter, parse_json
from .tat_post import flatten, postprocess
from .common import conf01

SCALES = ["", "thousand", "million", "billion", "percent"]


def items(path: Path) -> list[dict]:
    out = []
    for doc in json.loads(Path(path).read_text()):
        for q in doc["questions"]:
            out.append({"id": q["uid"], "doc": doc, "q": q})
    return out


def table_md(t: list[list[str]]) -> str:
    return "\n".join("| " + " | ".join(c.strip() for c in row) + " |" for row in t)


def context(doc: dict, paras: list[dict] | None = None) -> str:
    ps = paras if paras is not None else sorted(doc["paragraphs"], key=lambda p: p["order"])
    return "TABLE\n" + table_md(doc["table"]["table"]) + "\nPARAGRAPHS\n" + "\n".join(f"[P{p['order']}] {p['text']}" for p in ps)


ANS = ('Reply with JSON only: {"answer": a string, or a list of strings for multi-span answers, or a number, '
       '"scale": one of ' + json.dumps(SCALES) + ', "expression": arithmetic expression over context numbers if computed else "", '
       '"evidence": [verbatim table cells or sentence fragments you used], "confidence": your probability 0-1 that the answer is exactly right}. '
       'RULES (TAT-QA conventions): 1) "scale": if the figure (or the figures it is computed from) comes from a table or sentence '
       'stated "in thousands"/"in millions"/"$ million" etc, use that scale, also for differences, sums and averages of such figures; '
       'percentages, percentage changes and ratios -> "percent"; counts, years and plain text -> "". Do not repeat the scale word inside "answer". '
       '2) Round computed answers to 2 decimal places. Keep the sign (decreases are negative). Write numbers without $ or commas. '
       '3) For text/span answers copy the SHORTEST exact span from the context that answers the question, not the whole sentence; '
       'for "respective"/multiple values return a list of strings.')

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos}


def safe_eval(expr: str) -> float:
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and len(n.args) == 1 and not n.keywords:
            return _FUNCS[n.func.id](ev(n.args[0]))  # fix B10: abs(x) / calc(x) / round(x) wrappers were "does not evaluate"
        raise ValueError("unsupported expression")
    e = str(expr).replace("\u2212", "-").split("=")[0]  # fix B10: "a + b = c" -> "a + b"; unicode minus
    e = re.sub(r"\b[A-Z]{1,3}\$|[€£¥$%]|\b(?:thousand|million|billion)s?\b", "", e)
    e = re.sub(r"(?<=\d),(?=\d{3}\b)", "", e)  # thousands separators only; a top-level comma list stays a tuple -> error
    return ev(ast.parse(e, mode="eval"))


_FUNCS = {"abs": abs, "calc": float, "round": lambda x: float(round(x, 2))}


def _norm(s: str) -> str:
    """Quote normaliser shared by the Claim Gate and the citation scorer. Fix B3: thousands commas are removed
    (was: replaced by a space, so a quote '4351' never matched context '4,351') and table '|' separators are
    ignored (a row quoted without pipes never matched the '| a | b |' table rendering)."""
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(s).lower()).replace("|", " ")
    return re.sub(r"[\s$,()]+", " ", s).strip()


def gate(out: dict, ctx: str) -> list[str]:
    reasons, nctx, cnums = [], _norm(ctx), nums(ctx)
    for e in out.get("evidence") or []:
        if _norm(e) and _norm(e) not in nctx:
            reasons.append(f"evidence not found in context: {str(e)[:80]}")
    expr, ans = str(out.get("expression") or "").strip(), out.get("answer")
    if expr:
        for v in nums(expr):
            if v not in (100, 1000, 1e6) and not supported(abs(v), [abs(c) for c in cnums], free_small_ints=True):  # 100/1000 = percent/scale constants
                reasons.append(f"expression number {v} not in context")
        try:
            val = safe_eval(expr)
            a = nums(str(ans))
            if a and abs(a[0] - val) > max(0.01, 0.006 * abs(val)) and abs(a[0] - val * 100) > max(0.01, 0.006 * abs(val * 100)):
                reasons.append(f"answer {a[0]} != expression value {round(val, 4)}")
        except Exception as e:  # audit #5: keep the exception type in the logged reason
            reasons.append(f"expression does not evaluate ({type(e).__name__})")
    elif nums(str(ans)) and not traceable(str(ans), ctx):
        reasons.append("numeric answer not in context and no expression given")
    return reasons


def traceable(answer: str, ctx: str) -> bool:
    """System-agnostic check used for the unsupported-number rate: every number in the answer must
    be a context number, or the result of one +,-,*,/ or percentage change over two context numbers,
    or the mean of two (within rounding). Non-numeric answers are out of scope (True)."""
    a = nums(answer)
    if not a:
        return True
    c = sorted(set(abs(x) for x in nums(ctx)))[:120]
    derived = list(c)
    for x, y in itertools.permutations(c, 2):
        derived += [x + y, x - y, x * y, (x + y) / 2]
        if y:
            derived += [x / y, (x - y) / y]
    return all(supported(abs(v), derived, free_small_ints=True) for v in a)


def agent(it: dict, m: Meter) -> dict:
    doc, q = it["doc"], it["q"]
    ctx = context(doc)
    msgs = [{"role": "system", "content": "You are VeriAgent Why's evidence step. Answer only from the context; quote your evidence. " + ANS},
            {"role": "user", "content": ctx + "\nQUESTION: " + q["question"]}]
    log, decisions = [], []
    for g in range(2):
        out = m.call_json(msgs, "tat_agent", "s2", 600)
        reasons = gate(out, ctx)
        log.append({"round": g, "reasons": reasons, "out": {k: out.get(k) for k in ("answer", "scale", "expression", "evidence")}})  # audit trace
        # trace-fix 8: named fixed-policy decisions; STOP only means "gate still failing at the round cap"
        act = "ACCEPT" if not reasons else ("RETRY" if g == 0 else "STOP")
        decisions.append({"decision": "gate", "state": {"gate_round": g, "reasons": reasons}, "action": act,
                          "reason": {"ACCEPT": "gate passed", "RETRY": "fixed policy: retry once on any rejection", "STOP": "gate failed at round cap"}[act], "source": "fixed_policy"})
        if not reasons:
            break
        msgs = msgs + [{"role": "assistant", "content": json.dumps(out)[:2000]},
                       {"role": "user", "content": "Claim gate rejected: " + "; ".join(reasons) + ". Fix and answer again. " + ANS}]
    p = _pred(out, it)
    # deterministic confidence (declared in docs/BENCHMARKS.md): gate outcome x traceability, no model input
    det = tat_det(len(log), not reasons, traceable(str(p["answer"]), ctx), None)
    return {**p, "gate_passed": not reasons, "gate": log, "confidence_det": det, "policy_decisions": decisions,
            "conf_formula": "tat_det", "conf_inputs": {"gate_rounds": len(log), "gate_passed": not reasons, "traceable": traceable(str(p["answer"]), ctx), "rerank_p": None}}


def tat_det(rounds: int, passed: bool, tr: bool, rerank_p: float | None) -> float:
    """Declared deterministic confidence (agent / agent_mk*). trace-fix 8: same function used by the audit trace."""
    from .confidence import tat_det as f
    return f(rounds, passed, tr, rerank_p)


def rag(it: dict, m: Meter, k: int = 3) -> dict:
    doc, q = it["doc"], it["q"]
    ps = doc["paragraphs"]
    sc = bm25([p["text"] for p in ps], q["question"])
    top = [ps[i] for i in sorted(range(len(ps)), key=lambda i: -sc[i])[:k]]
    out = m.call_json([{"role": "system", "content": "Answer from the context. " + ANS},
                             {"role": "user", "content": context(doc, top) + "\nQUESTION: " + q["question"]}], "tat_rag", "s2", 600)
    return _pred(out, it)


def react(it: dict, m: Meter, max_steps: int = 4) -> dict:
    doc, q = it["doc"], it["q"]
    ctx = context(doc) + "\nQUESTION: " + q["question"]
    hist = ""
    for s in range(max_steps):
        a = m.call_json([{"role": "system", "content": "You are a ReAct analyst with one tool: calc (arithmetic). Each turn reply with JSON only: {\"thought\": str, \"action\": \"calc\", \"input\": expression} or {\"action\": \"final\"}."},
                               {"role": "user", "content": ctx + hist}], "tat_react", "s2", 400)
        if a.get("action") != "calc":
            break
        try:
            obs = str(round(safe_eval(str(a.get("input", ""))), 6))
        except Exception as e:
            obs = f"error {type(e).__name__}"
        hist += f"\nACTION {s + 1}: calc({a.get('input')})\nOBSERVATION {s + 1}: {obs}"
    out = m.call_json([{"role": "system", "content": "Give the final answer. " + ANS},
                             {"role": "user", "content": ctx + hist}], "tat_react_final", "s2", 600)
    return _pred(out, it)


def _pred(out: dict, it: dict | None = None) -> dict:
    """Raw model answer (flattened: fixes list-of-dicts TypeError) + deterministic scale/format post-step,
    applied identically to every system. Gold is never read here."""
    a = flatten(out.get("answer", ""))
    sc = out.get("scale") if out.get("scale") in SCALES else ""
    ev = out.get("evidence") or []
    ev = [str(e) for e in (flatten(ev) if isinstance(ev, (list, dict)) else [ev])]
    raw = {"answer": a, "scale": sc, "expression": str(out.get("expression", "") or "")}
    post = postprocess(raw, it["q"]["question"], it["doc"]) if it else raw
    rules = []
    if it:  # trace-fix 1: span post-rules selected on TAT-QA TRAIN only (scripts/fit_trace_fixes.py span)
        from . import fixes as FX
        a2, r1 = FX.split_years(post["answer"])
        a2, r2 = FX.span_extend(a2, [p["text"] for p in it["doc"]["paragraphs"]])
        rules = [x for x in (r1, r2) if x]
        post = {**post, "answer": a2}
    return {**post, "raw": raw, "evidence": ev, "confidence": conf01(out.get("confidence")), "span_rules": rules}


# fix B3: the model often 'quotes' reformatted cells ("Total Revenue $3,037,000 (2019)", "£m 2019: 0.8"), which the
# verbatim gate rejects; the controller path states the quoting format explicitly (and the retry restates it).
QUOTE_RULE = (' QUOTING: each "evidence" item must be copied character-for-character from the context: a whole table row as it '
              'appears between the | separators, or a sentence fragment. Do not add years, labels, colons or units that are not there.')


def agent_markov(it: dict, m: Meter, use_nv: bool = False, use_rerank: bool = False) -> dict:
    """agent + Markovian control (bench/markov.py): route NUMERIC (calculator steps, react's strength) or EVIDENCE
    (single call), optional DEEP final model from the NVIDIA classifier, expected-gain gate retry.
    Both routes keep the agent's quoted evidence, expression, Claim Gate and deterministic confidence."""
    from .markov import Controller, load_features, RELEVANCE_MIN
    doc, q = it["doc"], it["q"]
    ctl = Controller(use_nv, load_features("tatqa") if use_nv else None, "tatqa")
    ctx = context(doc)
    r = ctl.route(q["question"], it["id"])
    hist, seen, prev_obs = "", set(), None
    if r["path"] == "NUMERIC":
        for s in range(3):
            a = m.call_json([{"role": "system", "content": "You are VeriAgent Why's numeric step with one tool: calc (arithmetic). Each turn reply with JSON only: {\"thought\": str, \"action\": \"calc\", \"input\": expression over context numbers} or {\"action\": \"final\"}."},
                                   {"role": "user", "content": ctx + "\nQUESTION: " + q["question"] + hist}], "tat_mk_calc", "s2", 400)
            if a.get("action") != "calc":
                break
            try:
                obs = str(round(safe_eval(str(a.get("input", ""))), 6))
            except Exception as e:
                obs = f"error {type(e).__name__}"
            ek = re.sub(r"\s+", "", str(a.get("input", "")))
            if not ctl.calc_step(s + 1, ek, obs, seen, prev_obs):  # trace-fix 6: stop on repeated expression/observation
                break
            seen.add(ek); prev_obs = obs
            hist += f"\nACTION {s + 1}: calc({a.get('input')})\nOBSERVATION {s + 1}: {obs}"
    msgs = [{"role": "system", "content": "You are VeriAgent Why's evidence step. Answer only from the context; quote your evidence"  # fix B2: calc lines were quoted as evidence
             + ("; reuse the calculator expression that produced the answer, but quote ONLY verbatim context text as evidence, never "
                "ACTION/OBSERVATION calculator lines or computed values" if hist else "") + ". " + ANS + QUOTE_RULE},
            {"role": "user", "content": ctx + "\nQUESTION: " + q["question"] + hist}]
    log, rel, rerank_s = [], [], []
    for g in range(2):
        out = m.call_json(msgs, "tat_agent", "s2", 600, model=r["model"])
        reasons = gate(out, ctx)
        log.append({"round": g, "reasons": reasons, "out": {k: out.get(k) for k in ("answer", "scale", "expression", "evidence")}})  # audit trace
        retry = ctl.gate_retry(reasons, g, traceable(str(out.get("answer")), ctx))
        if use_rerank and not retry:
            from . import nv_rerank as NR
            try:
                t_r = time.time()
                p_rel = NR.rank(q["question"], [" | ".join(str(e) for e in (out.get("evidence") or [])) or "(no evidence)"])[0]
                rerank_s.append(round(time.time() - t_r, 3))
            except Exception as e:  # audit #5: logged, not swallowed
                p_rel = None
                m.parse_log.append({"tag": "rerank_error", "error": f"{type(e).__name__}: {str(e)[:100]}"})
            rel.append(p_rel)
            if ctl.evidence_check(p_rel, g, not reasons):
                msgs = msgs + [{"role": "assistant", "content": json.dumps(out)[:2000]},
                               {"role": "user", "content": "Evidence check: your quoted evidence does not look relevant to the question. Re-read the question, quote the exact cells/sentences that answer it, recompute if needed. " + ANS}]
                continue
        if not retry:
            break
        msgs = msgs + [{"role": "assistant", "content": json.dumps(out)[:2000]},
                       {"role": "user", "content": "Claim gate rejected: " + "; ".join(reasons) + ". Fix and answer again. " + ANS + QUOTE_RULE}]
    p = _pred(out, it)
    rp = rel[-1] if rel else None
    tr = traceable(str(p["answer"]), ctx)
    det = tat_det(len(log), not reasons, tr, rp)
    return {**p, "gate_passed": not reasons, "gate": log, "confidence_det": det, "route": r, "decisions": ctl.log, "calc_history": hist,
            "conf_formula": "tat_det", "conf_inputs": {"gate_rounds": len(log), "gate_passed": not reasons, "traceable": tr, "rerank_p": rp},
            "rerank_p": rel, "rerank_seconds": rerank_s}


def agent_vr(it: dict, m: Meter) -> dict:
    """fixed agent + verify-retry (bench/verify.py): Lightning generates, Super verifies (question + cited evidence only)."""
    from . import verify as V
    doc, q = it["doc"], it["q"]
    ctx = context(doc)
    base = [{"role": "system", "content": "You are VeriAgent Why's evidence step. Answer only from the context; quote your evidence. " + ANS},
            {"role": "user", "content": ctx + "\nQUESTION: " + q["question"]}]  # same prompt as fixed agent
    st = {"msgs": base, "last": None}

    def generate(fb):
        if fb and st["last"] is not None:
            st["msgs"] = st["msgs"] + [{"role": "assistant", "content": json.dumps(st["last"])[:2000]}, {"role": "user", "content": fb + " " + ANS}]
        out = m.call_json(st["msgs"], "tat_agent", "s2", 600)
        st["last"] = out
        return out

    def check(out):
        reasons = gate(out, ctx)
        ev = [str(e) for e in (out.get("evidence") or [])] if isinstance(out.get("evidence"), list) else [str(out.get("evidence") or "")]
        tr = traceable(str(out.get("answer")), " ".join(ev) or ctx)  # numbers traceable to the CITED evidence
        notes = reasons + ([] if tr else ["answer number not traceable to the cited evidence"]) + ([] if any(e.strip() for e in ev) else ["no evidence cited"])
        n = len(ev) + 3
        packet = {"answer": out.get("answer"), "scale": out.get("scale"), "claims": [{"text": str(out.get("answer")), "expression": out.get("expression")}],
                  "evidence": ev}
        return packet, 100.0 * max(0.0, 1 - len(notes) / n), notes

    out = V.loop(m, q["question"], generate, check)
    p = _pred(out, it)
    reasons = gate(out, ctx)
    glog = [{"round": a["attempt"] - 1, "reasons": [n for n in a["det_notes"]], "verify_score": a["score"]} for a in out["vr_attempts"]]
    return {**p, "confidence": out["confidence"], "confidence_det": out["confidence"], "gate_passed": not reasons, "gate": glog,
            "vr_decisions": out.get("vr_decisions", []), "vr_attempts": out.get("vr_attempts"), "conf_formula": "vr_score", "conf_inputs": {"vr_score": out["vr_score"]},
            **{k: out[k] for k in ("vr_score", "vr_attempts", "vr_best_attempt", "vr_n_attempts")}}


SYSTEMS = {"agent": agent, "agent_vr": agent_vr, "rag": rag, "react": react,
           "agent_mk": lambda it, m: agent_markov(it, m, False), "agent_mknv": lambda it, m: agent_markov(it, m, True),
           "agent_mkr": lambda it, m: agent_markov(it, m, True, True)}
from .verify2 import TAT_SYSTEMS as _V2  # noqa: E402  verify-v2 configs (docs/VERIFY_V2.md)
SYSTEMS.update(_V2)


def official_scores(data_dir: Path, gold_items: list[dict], preds: dict[str, list]) -> dict:
    """Run the official TaTQAEmAndF1 (downloaded tatqa_metric.py) over exactly the scored items."""
    sys.path.insert(0, str(data_dir))
    import tatqa_metric  # noqa: E402  (official, MIT)
    em = tatqa_metric.TaTQAEmAndF1()
    for it in gold_items:
        a, s = preds.get(it["id"], [None, None])
        em(ground_truth=it["q"], prediction=a, pred_scale=s)
    g_em, g_f1, g_scale, _ = em.get_overall_metric()
    return {"em": round(g_em, 4), "f1": round(g_f1, 4), "scale_acc": round(g_scale, 4)}


def item_em(data_dir: Path, it: dict, pred: dict) -> tuple[float, float]:
    sys.path.insert(0, str(data_dir))
    import tatqa_metric
    em = tatqa_metric.TaTQAEmAndF1()
    em(ground_truth=it["q"], prediction=pred.get("answer"), pred_scale=pred.get("scale"))
    e, f, _, _ = em.get_overall_metric()
    return e, f
import os as _os  # noqa: E402
if _os.environ.get("V71") == "1":  # V7.1 (development after the pre-registered run); never active in the frozen V7 config
    from .v71 import agent_mk71 as _mk71
    SYSTEMS["agent_mk71"] = _mk71
