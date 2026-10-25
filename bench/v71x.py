"""V7.1 ablation (development; docs/V71_ABLATION.md). Each arm = frozen V7 pipeline (agent_markov, no NV/rerank)
plus ONE isolated piece, selected by system name. Enabled only with V71=1. Gold is never read here: inputs are
it["id"], it["q"]["question"] and it["doc"]["table"/"paragraphs"] only (tests/test_v71x.py::test_no_gold_leakage).

Pieces (Alonso, 18:44):   f1 structured {answer_type,value,scale} | f2 extractive span (quote cut from source)
                          g5a gate sign | g5b gate empty/no-evidence BLOCK | g5c gate length/list/scale
Code Reviewer ideas, each on top of BASE = V7 + g5a + g5b:
  A trim: sentence answer -> literal sub-span (never adds tokens; exact spans unchanged)
  B detector: regex question type; 'which year' -> a year token present in the table header, else abstain
  C scale: only if predicted type arithmetic AND unit literally in the evidence/its header (or % / pct question)
  D lists: multi-span answers stay lists (split 'X and Y' / 'X, Y' numeric strings; never collapse)
"""
from __future__ import annotations
import json, re
from . import v71 as V

ARMS = {"mkx_f1": {"f1"}, "mkx_f2": {"f2"}, "mkx_g5a": {"g5a"}, "mkx_g5b": {"g5b"}, "mkx_g5c": {"g5c"},
        "mkx_base": {"g5a", "g5b"}, "mkx_A": {"g5a", "g5b", "A"}, "mkx_B": {"g5a", "g5b", "B"},
        "mkx_C": {"g5a", "g5b", "C"}, "mkx_D": {"g5a", "g5b", "D"}}

YEAR_TOK = re.compile(r"\b(?:19|20)\d{2}\b")
_ARITH = re.compile(r"\b(change|difference|average|mean|ratio|percentage|proportion|total|sum|increase|decrease|growth|"
                    r"how much (more|less|higher|lower)|what is the (sum|total))\b", re.I)


def qtype(question: str) -> str:
    """Deterministic question-type detector: year | count | arithmetic | list | span."""
    q = question.strip()
    if V.YEAR_Q.search(q) and not re.search(r"\bhow (much|many)\b", q, re.I):
        return "year"
    if re.match(r"\s*how many\b", q, re.I) and not _ARITH.search(q):
        return "count"
    if _ARITH.search(q) or re.match(r"\s*how much\b", q, re.I):
        return "arithmetic"
    if re.search(r"\b(what|which) (are|were)\b|\bwhat (items|components|types|segments|factors)\b|\blist\b", q, re.I):
        return "list"
    return "span"


def header_years(doc: dict) -> list[str]:
    tab = doc["table"]["table"]
    return YEAR_TOK.findall(" ".join(" ".join(r) for r in tab[:2]))


def trim_span(answer, question: str, srcs_text: list[str]):
    """A: cut a sentence answer to a literal sub-span: drop a leading subject that repeats question words plus its verb,
    and a trailing period. The result is always a substring of the input; an answer that is already an exact cell/
    short span (< 8 words, or no leading overlap) is returned unchanged. Returns (answer, rule|None)."""
    if not isinstance(answer, str) or len(answer.split()) < 8:
        return answer, None
    qw = {w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) > 2}
    m = re.match(r"^(?P<subj>.{3,120}?)\s+(?P<verb>is|are|was|were|represents|represent|relate to|relates to|consisted of|"
                 r"consists of|comprises|excluded|includes|include|means|refers to)\s+(?P<rest>.+)$", answer.strip(), re.I)
    out = answer
    if m:
        sw = [w for w in re.findall(r"[a-z0-9]+", m.group("subj").lower()) if len(w) > 2]
        if sw and sum(w in qw for w in sw) / len(sw) >= 0.5:
            out = m.group("rest")
    out = out.strip()
    if out.endswith(".") and not re.search(r"\b[A-Z][a-z]?\.$|\d\.$", out):
        out = out[:-1]
    if out == answer:
        return answer, None
    assert out in answer
    return out, "trim_to_subspan"


def split_list(answer):
    """D: '35,121 and 30,973' / '$3,800 and $6,690' -> list; lists are never collapsed. Returns (answer, rule|None)."""
    if isinstance(answer, list):
        return answer, None
    s = str(answer)
    parts = [p.strip() for p in re.split(r"\s*(?:;|\band\b|,\s(?=\D))\s*", s) if p.strip()]
    if len(parts) >= 2 and all(V._clean_num(p) is not None or YEAR_TOK.fullmatch(p) for p in parts):
        return parts, "split_numeric_list"
    return answer, None


def _unit_literal(evidence: list, doc: dict) -> str:
    txt = " ".join(str(e) for e in evidence or [])
    head = " ".join(" ".join(r) for r in doc["table"]["table"][:3])
    paras = " ".join(p["text"] for p in doc["paragraphs"])
    for src in (txt, head, paras if any(str(e)[:40] in paras for e in evidence or []) else ""):
        m = re.search(r"\b(?:in\s+)?(thousand|million|billion)s?\b|\$\s?(m|bn|k)\b|£\s?(m|000)\b|€\s?(m|000)\b", src, re.I)
        if m:
            g = (m.group(1) or {"m": "million", "bn": "billion", "k": "thousand", "000": "thousand"}.get((m.group(2) or m.group(3) or m.group(4) or "").lower(), ""))
            return g.lower()
    return ""


def run(it: dict, m, flags: set) -> dict:
    from . import tatqa as TQ
    from .markov import Controller
    from .tat_post import flatten
    doc, question = it["doc"], it["q"]["question"]
    ctl = Controller(False, None, "tatqa")
    ctx = TQ.context(doc)
    r = ctl.route(question, it["id"])
    hist, seen, prev_obs = "", set(), None
    if r["path"] == "NUMERIC":  # identical to agent_markov
        for s in range(3):
            a = m.call_json([{"role": "system", "content": "You are VeriAgent Why's numeric step with one tool: calc (arithmetic). Each turn reply with JSON only: {\"thought\": str, \"action\": \"calc\", \"input\": expression over context numbers} or {\"action\": \"final\"}."},
                             {"role": "user", "content": ctx + "\nQUESTION: " + question + hist}], "tat_mk_calc", "s2", 400)
            if a.get("action") != "calc":
                break
            try:
                obs = str(round(TQ.safe_eval(str(a.get("input", ""))), 6))
            except Exception as e:
                obs = f"error {type(e).__name__}"
            ek = re.sub(r"\s+", "", str(a.get("input", "")))
            if not ctl.calc_step(s + 1, ek, obs, seen, prev_obs):
                break
            seen.add(ek); prev_obs = obs
            hist += f"\nACTION {s + 1}: calc({a.get('input')})\nOBSERVATION {s + 1}: {obs}"
    if "f1" in flags:
        fmt = V.ANS71
    elif "f2" in flags:
        fmt = TQ.ANS + ' For text answers also return "quote": the literal text copied character-for-character from ONE table cell or paragraph (a list, one per item, for multi-span).'
    else:
        fmt = TQ.ANS
    msgs = [{"role": "system", "content": "You are VeriAgent Why's evidence step. Answer only from the context; quote your evidence"
             + ("; reuse the calculator expression that produced the answer, but quote ONLY verbatim context text as evidence, never "
                "ACTION/OBSERVATION calculator lines or computed values" if hist else "") + ". " + fmt + TQ.QUOTE_RULE},
            {"role": "user", "content": ctx + "\nQUESTION: " + question + hist}]
    qt = qtype(question)
    trace = {"flags": sorted(flags), "qtype_pred": qt, "rounds": [], "rules": []}
    log = []
    for g in range(2):
        out = m.call_json(msgs, "tat_agent71x" if flags & {"f1", "f2"} else "tat_agent", "s2", 700 if "f1" in flags else 600, model=r["model"])
        if "f1" in flags:
            ans, xlog = V.structure(out, doc)
            if not (flags & {"f2"}):
                ans["answer"] = out.get("value", out.get("answer"))
                xlog = []
        else:
            ans = {"answer": out.get("answer"), "scale": out.get("scale") if out.get("scale") in V.SCALES else "",
                   "expression": str(out.get("expression") or ""), "evidence": out.get("evidence") or [], "confidence": out.get("confidence")}
            a0 = ans["answer"]
            num = all(V._clean_num(x) is not None for x in (a0 if isinstance(a0, list) else [a0]))
            ans["answer_type"] = ("multi-span" if isinstance(a0, list) else "arithmetic" if (num and ans["expression"]) else
                                  "count" if qt == "count" else "span")
            xlog = []
            if "f2" in flags and ans["answer_type"] in ("span", "multi-span") and not num:
                q2 = out.get("quote") or a0
                cut = []
                for i, qq in enumerate(q2 if isinstance(q2, list) else [q2]):
                    e = V.extract(str(qq), V.sources(doc))
                    xlog.append({"step": "extract", "quote": str(qq)[:200], "found": e.get("found"), "method": e.get("method"), "cut": e.get("text")})
                    vals = a0 if isinstance(a0, list) else [a0]
                    cut.append(e["text"] if e.get("found") else str(vals[i] if i < len(vals) else qq))
                ans["answer"] = cut if isinstance(a0, list) else cut[0]
        legacy = {"answer": ans["answer"], "scale": ans["scale"], "expression": ans["expression"], "evidence": ans["evidence"]}
        reasons = TQ.gate(legacy, ctx)
        D = V.gate71(ans, question, doc, xlog)
        keep = (({"sign"} if "g5a" in flags else set()) | ({"non_empty_answer", "has_evidence"} if "g5b" in flags else set())
                | ({"single_number", "scale_vs_evidence", "span_length"} if "g5c" in flags else set()))
        D = [d for d in D if d["check"] in keep]
        reasons = reasons + V.failing(D)
        log.append({"round": g, "reasons": reasons, "out": legacy})
        trace["rounds"].append({"round": g, "answer_type": ans.get("answer_type"), "extract": xlog, "gate": D})
        if not ctl.gate_retry(reasons, g, TQ.traceable(str(ans["answer"]), ctx)):
            break
        msgs = msgs + [{"role": "assistant", "content": json.dumps(out)[:2000]},
                       {"role": "user", "content": "Traceability check rejected: " + "; ".join(reasons) + ". Fix and answer again. " + fmt + TQ.QUOTE_RULE}]
    blocked = "g5b" in flags and any(d["verdict"] == "BLOCK" for d in D)
    p = TQ._pred(legacy, it)  # V7 deterministic scale/format post-step + V7 span rules, unchanged
    a = p["answer"]
    if "A" in flags:
        a, rule = trim_span(a, question, [])
        if rule:
            trace["rules"].append({"rule": rule, "before": p["answer"], "after": a})
    if "D" in flags and qt in ("list", "span", "year"):
        a2, rule = split_list(a)
        if rule:
            trace["rules"].append({"rule": rule, "before": a, "after": a2}); a = a2
    if "B" in flags and qt == "year":
        hy = header_years(doc)
        items = a if isinstance(a, list) else [a]
        ys = [y for x in items for y in YEAR_TOK.findall(str(x)) if y in hy]
        if all(YEAR_TOK.fullmatch(str(x).strip()) for x in items):
            pass
        elif ys:
            a2 = ys if isinstance(a, list) and len(ys) > 1 else ys[0]
            trace["rules"].append({"rule": "year_from_header", "before": a, "after": a2}); a = a2
        else:
            trace["rules"].append({"rule": "year_abstain", "before": a, "after": ""}); a = ""
    sc = p["scale"]
    if "C" in flags:
        items = a if isinstance(a, list) else [a]
        isnum = bool(items) and all(V._clean_num(x) is not None for x in items)
        typ = "arithmetic" if (isnum and (qt == "arithmetic" or legacy["expression"])) else qt
        pct = bool(V._PCT_Q.search(question)) or any("%" in str(e) for e in legacy["evidence"] or [])
        lit = _unit_literal(legacy["evidence"], doc)
        sc2 = ("percent" if (pct and sc == "percent") else lit if (typ == "arithmetic" and lit) else "")
        if sc2 != sc:
            trace["rules"].append({"rule": "scale_literal_only", "before": sc, "after": sc2, "type": typ, "literal": lit})
        sc = sc2
    if blocked or a == "":
        a, sc = "", ""
    p = {**p, "answer": a, "scale": sc}
    tr = TQ.traceable(str(a), ctx)
    det = 0.0 if (blocked or a == "") else TQ.tat_det(len(log), not reasons, tr, None)
    return {**p, "gate_passed": not reasons, "gate": log, "confidence_det": det, "route": r, "decisions": ctl.log,
            "calc_history": hist, "conf_formula": "tat_det (0.0 if blocked/abstain)", "blocked": blocked,
            "v71": {"flag": "V71=1", "arm_flags": sorted(flags), "qtype_pred": qt, "rounds": trace["rounds"], "rules": trace["rules"],
                    "final_gate": D, "blocked": blocked}}


def systems() -> dict:
    return {name: (lambda f: (lambda it, m: run(it, m, f)))(fl) for name, fl in ARMS.items()}
