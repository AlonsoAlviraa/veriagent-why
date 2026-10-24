"""V8 (development; docs/V8_RESEARCH.md, docs/V8_ROUND_1.md). Enabled only with V8=1 as system ``agent_v8``.
One run per item records every arm so they are scored PAIRED on identical V7 outputs (no re-sampling of V7):
  v7      : frozen V7 pipeline (bench.tatqa.agent_markov, unchanged) -> output["answer"/"scale"] of V7 kept in v8.v7
  A  ptr  : one POINTER call at T=0 (TAT-LLM extractor->reasoner->executor / TagOp style): the model returns
            {"type", "args": [literal context texts], "expr": expression over a0..an, "scale_source": literal text or ""}.
            Executor: every arg must be found verbatim in the context; numbers are parsed from the literal; arithmetic
            is evaluated in Python; span answer = the literal arg(s); count = number of args. Invalid -> V7 answer.
            Scale: from scale_source only if that literal is in the context; else V7's deterministic infer_scale.
  B  sc   : K samples of the pointer stage at T=SC_T (declared), each executed; majority vote over valid executed
            answers (ties -> the T=0 pointer, then V7). Agreement features logged for confidence (fit offline on design).
  C  rep  : one repair call (T=0) ONLY when no pointer sample validates/executes; never for low confidence.
Gold is never read (tests/test_v8.py::test_no_gold_leakage_v8)."""
from __future__ import annotations
import json, os, re
from collections import Counter

K = int(os.environ.get("V8_K", "5"))
SC_T = float(os.environ.get("V8_SC_T", "0.7"))
TYPES = ["span", "multi-span", "arithmetic", "count"]

PTR = ('You are an extractor-reasoner. Do NOT compute the answer yourself. Reply with JSON only: '
       '{"type": one of ' + json.dumps(TYPES) + ', '
       '"args": [the exact texts copied character-for-character from the context that the answer uses: whole table cells '
       '(e.g. "$1,327.9" or "(35)") or the shortest sentence fragment; for span/multi-span these ARE the answer], '
       '"expr": for arithmetic an expression over a0, a1, ... (a0 = first arg) using + - * / ( ), e.g. "(a1 - a0) / a0 * 100"; else "", '
       '"scale_source": the exact context text that states the unit of the args (e.g. "(in thousands)", "$ million", "%"), or "" if none}. '
       'Percent changes/ratios expressed in % must multiply by 100. "change from Y1 to Y2" = Y2 - Y1.')


def _n(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).replace("\u2019", "'").replace("\u2013", "-").replace("\u2212", "-")).strip().lower()


def _num(lit: str) -> float | None:
    s = str(lit).strip().replace(",", "").replace("$", "").replace("£", "").replace("€", "").replace("%", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    if s in ("-", "—", ""):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def scale_of(src: str) -> str:
    s = _n(src)
    if not s:
        return ""
    if "%" in s or "percent" in s:
        return "percent"
    for w, u in (("billion", "billion"), ("million", "million"), ("thousand", "thousand"), ("$m", "million"), ("£m", "million"),
                 ("€m", "million"), ("$bn", "billion"), ("$'000", "thousand"), ("$000", "thousand"), ("'000", "thousand"), ("£000", "thousand")):
        if w in s:
            return u
    return ""


def execute(ptr: dict, ctx: str) -> dict:
    """Validate a pointer against the context and execute it. Returns {"ok", "answer", "scale", "why", "type"}."""
    t = ptr.get("type") if ptr.get("type") in TYPES else None
    args = ptr.get("args")
    args = [str(a) for a in args] if isinstance(args, list) else ([str(args)] if args not in (None, "") else [])
    nctx = _n(ctx)
    if not t:
        return {"ok": False, "why": "invalid type"}
    if not args:
        return {"ok": False, "why": "no args"}
    missing = [a for a in args if _n(a) not in nctx]
    if missing:
        return {"ok": False, "why": f"arg not in context: {missing[0][:60]}"}
    ss = str(ptr.get("scale_source") or "")
    sc = scale_of(ss) if ss and _n(ss) in nctx else ""
    sc_valid = bool(ss) and _n(ss) in nctx
    if t == "span":
        if len(args) != 1:
            return {"ok": False, "why": "span needs exactly one arg"}
        a = args[0].strip()
        return {"ok": True, "type": t, "answer": a, "scale": sc if _num(a) is not None else "", "scale_valid": sc_valid, "why": "literal span"}
    if t == "multi-span":
        return {"ok": True, "type": t, "answer": [a.strip() for a in args], "scale": sc if all(_num(a) is not None for a in args) else "",
                "scale_valid": sc_valid, "why": "literal spans"}
    if t == "count":
        return {"ok": True, "type": t, "answer": str(len(args)), "scale": "", "scale_valid": True, "why": "count of args"}
    vals = [_num(a) for a in args]
    if any(v is None for v in vals):
        return {"ok": False, "why": "non-numeric arg in arithmetic"}
    expr = str(ptr.get("expr") or "")
    if not re.fullmatch(r"[\sa0-9.+\-*/()]*", expr) or not expr.strip():
        return {"ok": False, "why": f"bad expr: {expr[:40]}"}
    e = re.sub(r"\ba(\d+)\b", lambda m: f"({vals[int(m.group(1))]!r})" if int(m.group(1)) < len(vals) else "BAD", expr)
    if "BAD" in e or re.search(r"[a-z]", e):
        return {"ok": False, "why": "expr references unknown arg"}
    try:
        from .tatqa import safe_eval
        v = safe_eval(e)
    except Exception as ex:
        return {"ok": False, "why": f"exec error {type(ex).__name__}"}
    v = round(v, 2)
    s = (f"{v:.2f}".rstrip("0").rstrip(".")) if v != int(v) else str(int(v))
    return {"ok": True, "type": t, "answer": s, "scale": sc, "scale_valid": sc_valid, "why": "executed", "value": v}


def key(ans) -> str:
    a = ans if isinstance(ans, list) else [ans]
    out = []
    for x in a:
        v = _num(x)
        out.append(f"{v:.2f}" if v is not None else _n(x).rstrip("."))
    return "|".join(sorted(out))


def finalize(ex: dict, question: str, doc: dict, v7_scale: str) -> dict:
    """Format like V7 (postprocess) but keep the pointer's literal-sourced scale when it validated; else V7's scale."""
    from .tat_post import postprocess
    pp = postprocess({"answer": ex["answer"], "scale": ex.get("scale") or "", "expression": ""}, question, doc)
    sc = ex.get("scale") if ex.get("scale_valid") and ex.get("scale") else (pp["scale"] or "")
    return {"answer": pp["answer"], "scale": sc}


def agent_v8(it: dict, m) -> dict:
    from . import tatqa as TQ
    from .verify2 import sampling
    question, doc = it["q"]["question"], it["doc"]
    v7 = TQ.agent_markov(it, m, use_nv=False)
    ctx = TQ.context(doc)
    msgs = [{"role": "system", "content": PTR + TQ.QUOTE_RULE}, {"role": "user", "content": ctx + "\nQUESTION: " + question}]
    calls0 = m.calls
    samples = []
    p0 = m.call_json(msgs, "v8_ptr", "s2", 500)
    samples.append({"t": 0.0, "raw": p0, "exec": execute(p0, ctx)})
    with sampling(SC_T):
        for _ in range(K):
            p = m.call_json(msgs, "v8_ptr_sc", "s2", 500)
            samples.append({"t": SC_T, "raw": p, "exec": execute(p, ctx)})
    v7_ans = {"answer": v7["answer"], "scale": v7["scale"]}
    # A: T=0 pointer
    e0 = samples[0]["exec"]
    A = finalize(e0, question, doc, v7["scale"]) if e0["ok"] else {**v7_ans, "fallback": True}
    # B: majority over valid executed samples (T=0 + K)
    valid = [s for s in samples if s["exec"]["ok"]]
    votes = Counter(key(s["exec"]["answer"]) for s in valid)
    if votes:
        top, nt = votes.most_common(1)[0]
        tied = [k for k, c in votes.items() if c == nt]
        pick = key(e0["answer"]) if e0["ok"] and key(e0["answer"]) in tied else top
        win = next(s for s in valid if key(s["exec"]["answer"]) == pick)
        B = finalize(win["exec"], question, doc, v7["scale"])
        agree = votes[pick] / len(samples)
    else:
        B, agree, pick = {**v7_ans, "fallback": True}, 0.0, None
    # C: one repair only when nothing validated
    rep = None
    if not valid:
        why = "; ".join(sorted({s["exec"]["why"] for s in samples}))[:300]
        r = m.call_json(msgs + [{"role": "assistant", "content": json.dumps(p0)[:1500]},
                                {"role": "user", "content": f"Pointer rejected by the executor: {why}. Copy args EXACTLY from the context and answer again. " + PTR}],
                        "v8_ptr_repair", "s2", 500)
        rep = {"raw": r, "exec": execute(r, ctx)}
    BC = finalize(rep["exec"], question, doc, v7["scale"]) if rep and rep["exec"]["ok"] else B
    feats = {"agree": round(agree, 4), "n_valid": len(valid), "k_total": len(samples), "ptr0_valid": bool(e0["ok"]),
             "ptr0_agrees_vote": bool(e0["ok"] and pick is not None and key(e0["answer"]) == pick),
             "v7_agrees_vote": bool(pick is not None and key(v7["answer"]) == pick),
             "v7_gate_passed": bool(v7.get("gate_passed")), "v7_conf_det": v7.get("confidence_det"),
             "type_vote": Counter(s["exec"].get("type") for s in valid).most_common(1)[0][0] if valid else None}
    out = {**v7, "answer": BC["answer"], "scale": BC["scale"],
           "v8": {"v7": v7_ans, "A": A, "B": B, "BC": BC, "features": feats, "K": K, "sc_t": SC_T,
                  "samples": [{"t": s["t"], "raw": {k: s["raw"].get(k) for k in ("type", "args", "expr", "scale_source")}, "exec": s["exec"]} for s in samples],
                  "repair": rep, "pointer_calls": m.calls - calls0}}
    return out


def enabled() -> bool:
    return os.environ.get("V8") == "1"
