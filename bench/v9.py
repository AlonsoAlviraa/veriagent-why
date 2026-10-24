"""V9 (development; docs/V9_RESEARCH.md, docs/V9_PREREG.md). V7 stays the answer system; V9 adds confidence signals.
Each idea is behind its own flag (all on for the pre-registered design run):
  V9_LOGPROBS=1  I1  token log-prob features of V7's final evidence call (LM-Polygraph MSP / mean / min / margin). 0 extra calls.
  V9_PTRUE=1     I2  P(True): evidence-conditioned verifier (Kadavath 2022) + verbalized confidence (Tian 2023). +1 call.
  V9_SC=1        I3  K samples of V7's exact final evidence prompt at T; semantic-entropy over answer clusters
                     (Farquhar 2024, discrete variant). +K calls. I3b (answer arm, scored separately): majority answer.
  V9_V8=1        re-run V8 pointer features on the same items (baseline for the V8 confidence model). +~6 calls.
I4 (conformal risk control) is offline: bench/v9_report.py."""
from __future__ import annotations

import contextlib
import json
import math
import os
from collections import Counter

K = int(os.environ.get("V9_K", "3"))
SC_T = float(os.environ.get("V9_SC_T", "0.7"))


def flag(name: str) -> bool:
    return os.environ.get(name, "1") == "1"


@contextlib.contextmanager
def logprobs():
    from . import nebius
    old = nebius.LOGPROBS
    nebius.LOGPROBS = True
    try:
        yield
    finally:
        nebius.LOGPROBS = old


# ---------- I1: token log-prob features (pure, unit-tested) ----------
def _answer_span(lp: list[dict], content: str) -> list[dict]:
    """Tokens that belong to the value of the "answer" key in the JSON reply (best effort; falls back to all tokens)."""
    pos, spans = 0, []
    for x in lp:
        t = x.get("t") or ""
        spans.append((pos, pos + len(t)))
        pos += len(t)
    text = "".join(x.get("t") or "" for x in lp)
    i = text.find('"answer"')
    if i < 0:
        return lp
    j = text.find(":", i)
    end = len(text)
    for k2 in ('"scale"', '"expression"', '"evidence"', '"confidence"'):
        e = text.find(k2, j)
        if 0 <= e < end:
            end = e
    sel = [x for x, (a, b) in zip(lp, spans) if b > j + 1 and (a + b) / 2 < end and (x.get("t") or "").strip(' ",:[]')]
    return sel or lp


def lp_features(lp: list[dict] | None, content: str = "") -> dict:
    if not lp:
        return {"lp_ok": False}
    a = _answer_span(lp, content)
    v = [x["lp"] for x in a if x.get("lp") is not None]
    allv = [x["lp"] for x in lp if x.get("lp") is not None]
    margins = []
    for x in a:
        top = sorted((t[1] for t in (x.get("top") or []) if t and t[1] is not None), reverse=True)
        if len(top) >= 2:
            margins.append(math.exp(top[0]) - math.exp(top[1]))
    if not v:
        return {"lp_ok": False}
    return {"lp_ok": True, "ans_msp": math.exp(sum(v)),            # sequence prob of the answer tokens (MSP)
            "ans_mean_lp": sum(v) / len(v), "ans_min_lp": min(v),
            "ans_min_margin": min(margins) if margins else None,
            "seq_mean_lp": sum(allv) / len(allv), "n_ans_tok": len(v)}


# ---------- I2: P(True) ----------
PTRUE = ('You are a strict verifier of financial QA answers. Given the CONTEXT, the QUESTION and a PROPOSED ANSWER, decide if the '
         'proposed answer (value AND scale) is exactly correct. Reply with JSON only: {"verdict": "A" or "B", "confidence": integer 0-100} '
         'where A = correct, B = incorrect, and confidence = your probability (0-100) that the proposed answer is correct.')


def ptrue_from(lp: list[dict] | None, out: dict) -> dict:
    """P(A) renormalised over {A,B} at the verdict token; falls back to the sampled verdict."""
    verdict = str(out.get("verdict", "")).strip().upper()[:1]
    try:
        verbal = max(0.0, min(1.0, float(out.get("confidence")) / 100))
    except (TypeError, ValueError):
        verbal = None
    p = None
    for x in lp or []:
        t = (x.get("t") or "").strip(' "')
        if t in ("A", "B"):
            d = {str(tok).strip(' "'): l for tok, l in (x.get("top") or []) if tok is not None and l is not None}
            pa, pb = math.exp(d["A"]) if "A" in d else 0.0, math.exp(d["B"]) if "B" in d else 0.0
            if pa + pb > 0:
                p = pa / (pa + pb)
            break
    if p is None and verdict in ("A", "B"):
        p = 1.0 if verdict == "A" else 0.0
    return {"ptrue": p, "verdict": verdict or None, "verbal": verbal, "ptrue_from_lp": p not in (None, 0.0, 1.0) or bool(lp)}


# ---------- I3: semantic entropy over answer clusters ----------
def akey(ans, scale) -> str:
    from .v8 import key
    return key(ans) + "#" + (scale or "")


def sc_features(v7_key: str, sample_keys: list[str]) -> dict:
    allk = [v7_key] + sample_keys
    c = Counter(allk)
    n = len(allk)
    se = -sum((k / n) * math.log(k / n) for k in c.values())
    top, nt = c.most_common(1)[0]
    pick = v7_key if c[v7_key] == nt else top  # V7 wins ties
    return {"sem_entropy": se, "n_clusters": len(c), "v7_share": c[v7_key] / n,
            "sample_agree_v7": sum(k == v7_key for k in sample_keys) / max(1, len(sample_keys)), "sc_pick": pick}


def agent_v9(it: dict, m) -> dict:
    from . import tatqa as TQ
    from .verify2 import sampling
    q, doc = it["q"]["question"], it["doc"]
    m.__dict__["lp_log"] = []
    with logprobs():
        v7 = TQ.agent_markov(it, m, use_nv=False)
    fin = [r for r in m.lp_log if r["tag"] == "tat_agent"]
    v9: dict = {"features": {}}
    calls0 = m.calls
    if flag("V9_LOGPROBS"):
        v9["features"].update(lp_features(fin[-1]["lp"], fin[-1]["content"]) if fin else {"lp_ok": False})
    if flag("V9_PTRUE"):
        ctx = TQ.context(doc)
        prop = json.dumps({"answer": v7["answer"], "scale": v7["scale"]})
        n0 = len(m.lp_log)
        with logprobs():
            o = m.call_json([{"role": "system", "content": PTRUE},
                             {"role": "user", "content": ctx + "\nQUESTION: " + q + "\nPROPOSED ANSWER: " + prop}], "v9_ptrue", "s2", 60)
        lp = m.lp_log[-1]["lp"] if len(m.lp_log) > n0 else None
        v9["features"].update(ptrue_from(lp, o))
    v7k = akey(v7["answer"], v7["scale"])
    if flag("V9_SC") and m.__dict__.get("v9_final"):
        msgs, model = m.v9_final
        samples = []
        with sampling(SC_T):
            for _ in range(K):
                o = m.call_json(msgs, "v9_sc", "s2", 600, model=model)
                p = TQ._pred(o, it)
                samples.append({"answer": p["answer"], "scale": p["scale"], "key": akey(p["answer"], p["scale"])})
        f = sc_features(v7k, [s["key"] for s in samples])
        v9["features"].update({k: v for k, v in f.items() if k != "sc_pick"})
        win = next((s for s in samples if s["key"] == f["sc_pick"]), None)
        v9["I3b"] = {"answer": win["answer"], "scale": win["scale"]} if win and f["sc_pick"] != v7k else {"answer": v7["answer"], "scale": v7["scale"]}
        v9["I3b_changed"] = f["sc_pick"] != v7k
        v9["samples"] = samples
    v9["extra_calls_v9"] = m.calls - calls0
    out = {**v7}
    if flag("V9_V8"):
        from . import v8
        # pointer features only; V8's answer is NOT used. Re-use agent_v8 logic minus its own V7 call.
        _orig = TQ.agent_markov
        TQ.agent_markov = lambda *a, **k: v7
        try:
            c1 = m.calls
            r8 = v8.agent_v8(it, m)
        finally:
            TQ.agent_markov = _orig
        v9["v8_features"] = r8["v8"]["features"]
        v9["v8_calls"] = m.calls - c1
    out["answer"], out["scale"] = v7["answer"], v7["scale"]  # V7 answer, unchanged
    out["v9"] = v9
    m.__dict__.pop("lp_log", None)
    m.__dict__.pop("v9_final", None)
    return out


def enabled() -> bool:
    return os.environ.get("V9") == "1"
