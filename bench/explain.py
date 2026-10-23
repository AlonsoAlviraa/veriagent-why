"""Track 02 explainability metrics, applied identically to agent, rag and react.
Deterministic unless noted. Definitions are in docs/BENCHMARKS.md ("Explainability metrics").

InsightBench (claims = final insights, each with cited evidence ids into the system's own evidence store:
agent query results q1.., rag retrieved row ids, react observation numbers):
- citation_precision: cited ids that exist in the store AND contain >=1 of the claim's numbers
  (directly or recomputable from that citation); for number-free claims existence suffices. / all citations.
- claim_traceability: claims with >=1 valid citation whose every number is direct/derived from the cited evidence. / all claims.
- unsupported_number_rate: numbers in final insights+summary not direct/derived from ANY evidence the system saw. / all numbers.
- faithfulness (LLM judge, sample): "is the why entailed by the evidence?" 1-10 -> /10.
TAT-QA (claim = the answer, citations = verbatim evidence quotes):
- citation_precision: quotes found in the context that contain a number used by the answer/expression
  (text answers: share a token with the answer). / all quotes.
- claim_traceability: answer recomputable from the cited quotes' numbers (text answers: contained in a cited quote).
- unsupported_number: answer not traceable to the whole context (the v1 metric).
Calibration (ECE, Brier) is computed in bench.report from per-item confidence vs correctness.
"""
from __future__ import annotations
import re
from .common import derived_ok, derived_pool, nums, supported


_CACHE: dict = {}


def _supp(v: float, src: list[str]) -> bool:
    key = tuple(src)
    if key not in _CACHE:
        if len(_CACHE) > 256:
            _CACHE.clear()
        a = [x for s in src for x in nums(s)]
        _CACHE[key] = (a, derived_pool(a))
    a, pool = _CACHE[key]
    return supported(v, a) or derived_ok(v, pool)


def insight_metrics(out: dict) -> dict:
    store = out.get("evidence_store") or {}
    claims = out.get("claims") or [{"text": t, "evidence": []} for t in out.get("insights") or []]
    cit = cit_ok = tr = 0
    for c in claims:
        ev = [e for e in (c.get("evidence") or [])]
        ns = nums(c["text"])
        valid = []
        for e in ev:
            cit += 1
            if e in store and (not ns or any(_supp(v, [store[e]]) for v in ns)):
                cit_ok += 1
                valid.append(e)
        if valid and all(_supp(v, [store[e] for e in ev if e in store]) for v in ns):
            tr += 1
    allsrc = list(store.values())
    text_nums = [v for c in claims for v in nums(c["text"])] + nums(out.get("summary") or "")
    un = sum(not _supp(v, allsrc) for v in text_nums)
    return {"claims": len(claims), "citations": cit, "citations_valid": cit_ok, "claims_traceable": tr,
            "numbers": len(text_nums), "numbers_unsupported": un}


def _n(s: str) -> str:
    return re.sub(r"[\s$,()]+", " ", str(s).lower()).strip()


def tat_metrics(out: dict, ctx: str) -> dict:
    ev = [str(e) for e in (out.get("evidence") or []) if str(e).strip()]
    raw = out.get("raw") or out
    ans = raw.get("answer")
    ans_s = " ".join(ans) if isinstance(ans, list) else str(ans or "")
    used = nums(str(raw.get("expression") or "")) or nums(ans_s)
    nctx = _n(ctx)
    ok = 0
    for e in ev:
        if _n(e) and _n(e) in nctx:
            if used:
                if any(supported(abs(u), [abs(x) for x in nums(e)], free_small_ints=False) for u in used):
                    ok += 1
            elif set(_n(ans_s).split()) & set(_n(e).split()):
                ok += 1
    found = [e for e in ev if _n(e) and _n(e) in nctx]
    a = nums(ans_s)
    if a:
        tr = bool(found) and all(_supp(v, found) for v in a)
    else:
        tr = bool(ans_s.strip()) and any(_n(ans_s) in _n(e) for e in found)
    return {"citations": len(ev), "citations_valid": ok, "claims": 1, "claims_traceable": int(tr)}


FAITH_SYSTEM = "You are a strict auditor of analytical explanations. You check whether an explanation is supported by the evidence it was given."
FAITH_TEMPLATE = """EVIDENCE (query results / rows the analyst saw):
{evidence}

EXPLANATION (insights and summary written by the analyst):
{explanation}

Rate 1-10 how faithful the explanation is to the evidence: 10 = every claim and every stated cause ("why") is directly supported or validly computed from the evidence; 1 = mostly unsupported or contradicted. Ignore style and completeness; judge only support. Reply with only <rating>N</rating>."""


def faithfulness(m, out: dict, max_chars: int = 9000) -> float | None:
    store = out.get("evidence_store") or {}
    ev = "\n".join(f"[{k}] {v[:1500]}" for k, v in store.items())[:max_chars]
    ex = "\n".join(f"- {t}" for t in out.get("insights") or []) + "\nSUMMARY: " + (out.get("summary") or "")
    if not (out.get("insights") or out.get("summary")):
        return None
    r = m.call([{"role": "system", "content": FAITH_SYSTEM}, {"role": "user", "content": FAITH_TEMPLATE.format(evidence=ev or "(none)", explanation=ex[:4000])}], "faith", "s2", 50)
    x = re.findall(r"<rating>\s*(\d+)\s*</rating>", r or "") or re.findall(r"\b(10|[1-9])\b", r or "")
    return int(x[0]) / 10 if x else None
