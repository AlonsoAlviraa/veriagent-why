"""V7.1 (development after the pre-registered V7 run; docs/V71_DEV_RESULTS.md). Enabled only with V71=1, as the
separate system ``agent_mk71``. The frozen V7 config (agent_mk, bench/freeze/test500_v1.json) is not changed.

Changes over agent_mk (same router, calculator steps, model, T=0, deterministic confidence formula):
 1) Structured output: the Writer returns {"answer_type": span|multi-span|arithmetic|count, "value", "scale",
    "quote", "expression", "evidence", "confidence"} following TAT-QA's official answer format.
 2) Extractive spans: for span/multi-span the model returns the literal quote(s); the code cuts them from the source
    (table cell or paragraph) with fuzzy matching. Not found -> fall back to the model's value, logged in the trace.
 5) Expanded claim gate (checks below), every decision with its reason in output["v71"]["gate"] -> audit.json.
Gold is never read here.
"""
from __future__ import annotations
import difflib, json, os, re, time
from .common import nums
from .tat_post import _unit_of, _PCT_Q

ANSWER_TYPES = ["span", "multi-span", "arithmetic", "count"]
SCALES = ["", "thousand", "million", "billion", "percent"]
FUZZY_MIN = 0.85
YEAR_Q = re.compile(r"\b(which|what)\s+(fiscal\s+)?years?\b|\bin which (fiscal )?years?\b", re.I)
DIFF_Q = re.compile(r"\bdifference\b", re.I)
CHANGE_Q = re.compile(r"\bchange\b", re.I)

ANS71 = ('Reply with JSON only: {"answer_type": one of ' + json.dumps(ANSWER_TYPES) + ', '
         '"value": a number for arithmetic/count, a string for span, a list of strings for multi-span, '
         '"quote": for span/multi-span the literal text copied character-for-character from ONE table cell or paragraph '
         '(a list of quotes for multi-span, one per answer item), else "", '
         '"scale": one of ' + json.dumps(SCALES) + ', "expression": arithmetic expression over context numbers if computed else "", '
         '"evidence": [verbatim table rows or sentence fragments you used], "confidence": your probability 0-1 that the answer is exactly right}. '
         'RULES (TAT-QA official format): 1) "scale" is the unit the source states for the figures (in thousands/millions/$m...), also for '
         'differences, sums and averages of such figures; percentages, percentage changes and ratios -> "percent"; counts, years and text -> "". '
         'Never write the scale word inside "value". 2) arithmetic: ONE number, rounded to 2 decimals, no $ or commas; never a list. '
         '"change from Y1 to Y2" = value(Y2) - value(Y1) and keeps its sign. 3) span: the SHORTEST quote that answers the question '
         '(a year question -> only the year). 4) count: the number of items as an integer.')


def _clean_num(v) -> float | None:
    s = str(v).replace(",", "").replace("$", "").replace("%", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    try:
        x = float(s.strip("()"))
    except ValueError:
        return None
    return -x if neg else x


def sources(doc: dict) -> list[dict]:
    """Every extractable source unit: table cells and paragraphs (with their original text)."""
    out = []
    for r, row in enumerate(doc["table"]["table"]):
        for c, cell in enumerate(row):
            if str(cell).strip():
                out.append({"kind": "cell", "loc": f"r{r}c{c}", "text": str(cell).strip()})
    for p in sorted(doc["paragraphs"], key=lambda p: p["order"]):
        out.append({"kind": "paragraph", "loc": f"P{p['order']}", "text": p["text"]})
    return out


def _n(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).lower().replace("\u2019", "'").replace("\u2013", "-")).strip()


def extract(quote: str, srcs: list[dict]) -> dict:
    """Cut `quote` out of the source. 1) case/space-insensitive exact substring, 2) fuzzy window
    (difflib ratio >= FUZZY_MIN over same-length windows). Returns the ORIGINAL source text of the match."""
    q = _n(quote)
    if not q:
        return {"found": False, "method": "empty_quote"}
    for s in srcs:  # cells first: an exact cell match is the tightest span
        t = _n(s["text"])
        i = t.find(q)
        if i >= 0:
            # map back to original characters (normalisation only collapses spaces/case -> re-find with a regex)
            pat = r"\s+".join(re.escape(w) for w in quote.split())
            m = re.search(pat, s["text"], re.I)
            span = m.group(0) if m else s["text"][i:i + len(quote)]
            return {"found": True, "method": "exact", "kind": s["kind"], "loc": s["loc"], "text": span, "ratio": 1.0}
    best = None
    qw = q.split()
    for s in srcs:
        words = s["text"].split()
        L = len(qw)
        for k in {max(1, L - 1), L, L + 1}:
            for j in range(0, max(1, len(words) - k + 1)):
                cand = " ".join(words[j:j + k])
                r = difflib.SequenceMatcher(None, q, _n(cand)).ratio()
                if not best or r > best["ratio"]:
                    best = {"kind": s["kind"], "loc": s["loc"], "text": cand.strip(" ,;.:"), "ratio": round(r, 3)}
    if best and best["ratio"] >= FUZZY_MIN:
        return {"found": True, "method": "fuzzy", **best}
    return {"found": False, "method": "not_found", "best_ratio": best["ratio"] if best else None}


def structure(out: dict, doc: dict) -> tuple[dict, list[dict]]:
    """Model JSON -> answer in the legacy {"answer","scale","expression","evidence"} shape, with extraction log."""
    at = out.get("answer_type") if out.get("answer_type") in ANSWER_TYPES else None
    val = out.get("value", out.get("answer"))
    sc = out.get("scale") if out.get("scale") in SCALES else ""
    log = []
    if at in ("span", "multi-span"):
        quotes = out.get("quote")
        quotes = quotes if isinstance(quotes, list) else ([quotes] if quotes not in (None, "") else [])
        vals = val if isinstance(val, list) else [val]
        if not quotes:
            quotes = [v for v in vals if v not in (None, "")]
            log.append({"step": "extract", "result": "no quote returned; using value as quote"})
        cut = []
        srcs = sources(doc)
        for i, qt in enumerate(quotes):
            e = extract(str(qt), srcs)
            log.append({"step": "extract", "quote": str(qt)[:200], **{k: e.get(k) for k in ("found", "method", "kind", "loc", "ratio", "best_ratio")},
                        "cut": e.get("text") if e.get("found") else None})
            fb = str(vals[i]) if i < len(vals) and vals[i] not in (None, "") else str(qt)
            cut.append(e["text"] if e.get("found") else fb)
            if not e.get("found"):
                log.append({"step": "extract_fallback", "reason": "quote not found in source (exact or fuzzy); kept model value", "value": fb[:200]})
        ans = cut if at == "multi-span" else (cut[0] if cut else "")
        if at == "multi-span" and len(cut) == 1:
            ans = cut
    else:
        ans = val
    return {"answer": ans, "scale": sc, "expression": str(out.get("expression") or ""), "evidence": out.get("evidence") or [],
            "answer_type": at, "confidence": out.get("confidence")}, log


def _evidence_unit(evidence: list, doc: dict) -> str:
    """Unit stated by the source of the cited evidence: table header rows (+ any paragraph statement) if the evidence
    is a table row/cell, or the paragraph that contains it. '' if none stated."""
    tab = doc["table"]["table"]
    head = " ".join(" ".join(r) for r in tab[:3])
    paras = [p["text"] for p in doc["paragraphs"]]
    table_txt = _n(" ".join(" ".join(r) for r in tab))
    units = []
    for e in evidence or []:
        ne = _n(str(e).replace("|", " "))
        if not ne:
            continue
        toks = [t for t in ne.split() if t]
        in_table = bool(toks) and all(t in table_txt for t in toks[:6])
        if in_table:
            u = _unit_of(head) or next((_unit_of(p) for p in paras if re.search(r"in (thousands|millions|billions)", p, re.I)), "")
        else:
            u = next((_unit_of(p) for p in paras if ne[:60] in _n(p)), "") or _unit_of(str(e))
        units.append(u)
    units = [u for u in units if u]
    return units[0] if units else ""


def gate71(ans: dict, question: str, doc: dict, log_extract: list[dict]) -> list[dict]:
    """Expanded claim gate. Each check -> {"check", "verdict": PASS|FAIL|BLOCK|SKIP, "reason"}. BLOCK = the answer
    must not be emitted as supported (empty answer / no evidence; fix for item c3ef3efb4a4e)."""
    a, at, sc = ans["answer"], ans.get("answer_type"), ans.get("scale") or ""
    ev = [str(e) for e in (ans.get("evidence") or []) if str(e).strip()]
    items = a if isinstance(a, list) else [a]
    items = [str(x).strip() for x in items if x is not None and str(x).strip()]
    D = []

    def add(check, verdict, reason):
        D.append({"check": check, "verdict": verdict, "reason": reason})

    add("non_empty_answer", "PASS" if items else "BLOCK", "answer present" if items else "empty answer: blocked")
    add("has_evidence", "PASS" if ev else "BLOCK", f"{len(ev)} evidence item(s) cited" if ev else "no evidence cited: blocked")
    add("answer_type", "PASS" if at else "FAIL", f"answer_type={at}" if at else "missing/invalid answer_type")
    # list vs single number for arithmetic/count
    if at in ("arithmetic", "count"):
        ok = not isinstance(a, list) and _clean_num(a) is not None
        add("single_number", "PASS" if ok else "FAIL", "one number" if ok else f"{at} answer must be ONE number, got {str(a)[:60]}")
    else:
        add("single_number", "SKIP", "not arithmetic/count")
    # scale vs evidence
    numeric_span = at in ("span", "multi-span") and bool(items) and all(_clean_num(x) is not None for x in items)
    if (at == "arithmetic" or numeric_span) and items:
        pct_q = bool(_PCT_Q.search(question)) or bool(re.search(r"\bratio\b|\brate\b", question, re.I))
        u = _evidence_unit(ev, doc)
        if pct_q:
            add("scale_vs_evidence", "PASS" if sc == "percent" or re.search(r"\bratio\b", question, re.I) else "FAIL",
                "percentage question" + ("" if sc == "percent" else f": scale '{sc}' should be 'percent'"))
        elif u and sc == "":
            add("scale_vs_evidence", "FAIL", f"evidence source states figures in {u}s but scale is empty")
        elif u and sc not in (u, "percent"):
            add("scale_vs_evidence", "FAIL", f"evidence source states {u}s but scale is '{sc}'")
        else:
            add("scale_vs_evidence", "PASS", f"evidence unit '{u}' / scale '{sc}'")
    elif at in ("span", "multi-span") and sc not in ("",):
        add("scale_vs_evidence", "PASS" if nums(" ".join(items)) else "FAIL",
            "span with numeric content" if nums(" ".join(items)) else f"text span cannot carry scale '{sc}'")
    else:
        add("scale_vs_evidence", "SKIP", "no scale to check")
    # sign coherence
    v = _clean_num(a) if at == "arithmetic" and not isinstance(a, list) else None
    if v is not None:
        expr_v = None
        if ans.get("expression"):
            try:
                from .tatqa import safe_eval
                expr_v = safe_eval(ans["expression"])
            except Exception:
                expr_v = None
        if expr_v is not None and v != 0 and expr_v != 0 and (v > 0) != (expr_v > 0):
            add("sign", "FAIL", f"answer sign ({v}) differs from expression value ({round(expr_v, 4)})")
        elif DIFF_Q.search(question) and not CHANGE_Q.search(question) and v < 0:
            add("sign", "FAIL", "'difference' question with a negative answer (93% of TAT-QA train 'difference' answers are non-negative); check operand order")
        else:
            add("sign", "PASS", "sign coherent with expression/question")
    else:
        add("sign", "SKIP", "not a single arithmetic number")
    # span length / year format
    if at in ("span", "multi-span") and items:
        cuts = [x for x in log_extract if x.get("step") == "extract" and x.get("found")]
        too_long = [x for x in items if cuts and not any(len(x) <= len(c.get("cut") or "") + 1 for c in cuts)]
        if YEAR_Q.search(question) and not all(re.fullmatch(r"(19|20)\d{2}", x) for x in items):
            add("span_length", "FAIL", "year question: each answer item must be only a year")
        elif too_long:
            add("span_length", "FAIL", f"answer longer than the cited span: {too_long[0][:60]}")
        else:
            add("span_length", "PASS", "answer within cited span")
    else:
        add("span_length", "SKIP", "not a span answer")
    return D


def repair(ans: dict, question: str) -> tuple[dict, list[dict]]:
    """Deterministic format repairs, each logged: year question with exactly one year inside a span -> that year."""
    rep = []
    a = ans["answer"]
    if ans.get("answer_type") in ("span", "multi-span") and YEAR_Q.search(question):
        items = a if isinstance(a, list) else [a]
        new = []
        for x in items:
            ys = re.findall(r"\b(?:19|20)\d{2}\b", str(x))
            new.append(ys[0] if len(ys) == 1 and not re.fullmatch(r"(19|20)\d{2}", str(x).strip()) else x)
        if new != items:
            rep.append({"rule": "year_only", "before": a, "after": new if isinstance(a, list) else new[0]})
            ans = {**ans, "answer": new if isinstance(a, list) else new[0]}
    return ans, rep


def failing(D: list[dict]) -> list[str]:
    return [f"{d['check']}: {d['reason']}" for d in D if d["verdict"] in ("FAIL", "BLOCK")]


def agent_mk71(it: dict, m) -> dict:
    from . import tatqa as TQ
    from .markov import Controller
    from .tat_post import flatten
    from .common import conf01
    doc, q = it["doc"], it["q"]
    ctl = Controller(False, None, "tatqa")
    ctx = TQ.context(doc)
    r = ctl.route(q["question"], it["id"])
    hist, seen, prev_obs = "", set(), None
    if r["path"] == "NUMERIC":  # identical to agent_mk
        for s in range(3):
            a = m.call_json([{"role": "system", "content": "You are VeriAgent Why's numeric step with one tool: calc (arithmetic). Each turn reply with JSON only: {\"thought\": str, \"action\": \"calc\", \"input\": expression over context numbers} or {\"action\": \"final\"}."},
                             {"role": "user", "content": ctx + "\nQUESTION: " + q["question"] + hist}], "tat_mk_calc", "s2", 400)
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
    msgs = [{"role": "system", "content": "You are VeriAgent Why's evidence step. Answer only from the context; quote your evidence"
             + ("; reuse the calculator expression that produced the answer, but quote ONLY verbatim context text as evidence, never "
                "ACTION/OBSERVATION calculator lines or computed values" if hist else "") + ". " + ANS71 + TQ.QUOTE_RULE},
            {"role": "user", "content": ctx + "\nQUESTION: " + q["question"] + hist}]
    log, rounds = [], []
    for g in range(2):
        out = m.call_json(msgs, "tat_agent71", "s2", 700, model=r["model"])
        ans, xlog = structure(out, doc)
        ans, rep = repair(ans, q["question"])
        legacy = {"answer": ans["answer"], "scale": ans["scale"], "expression": ans["expression"], "evidence": ans["evidence"]}
        reasons = TQ.gate(legacy, ctx)
        D = gate71(ans, q["question"], doc, xlog)
        reasons = reasons + failing(D)
        log.append({"round": g, "reasons": reasons, "out": legacy})
        rounds.append({"round": g, "raw": {k: out.get(k) for k in ("answer_type", "value", "quote", "scale", "expression")}, "extract": xlog,
                       "repairs": rep, "gate": D})
        retry = ctl.gate_retry(reasons, g, TQ.traceable(str(ans["answer"]), ctx))
        if not retry:
            break
        msgs = msgs + [{"role": "assistant", "content": json.dumps(out)[:2000]},
                       {"role": "user", "content": "Claim gate rejected: " + "; ".join(reasons) + ". Fix and answer again. " + ANS71 + TQ.QUOTE_RULE}]
    blocked = any(d["verdict"] == "BLOCK" for d in D)
    ev = [str(e) for e in (flatten(ans["evidence"]) if isinstance(ans["evidence"], (list, dict)) else [ans["evidence"]])]
    a_final = flatten(ans["answer"]) if not blocked else ""
    if isinstance(a_final, list) and ans.get("answer_type") in ("arithmetic", "count") and len(a_final) == 1:
        a_final = a_final[0]
    raw = {"answer": a_final, "scale": ans["scale"], "expression": ans["expression"]}
    p_answer, p_scale = a_final, (ans["scale"] if not blocked else "")
    _its = a_final if isinstance(a_final, list) else [a_final]
    numeric = bool(_its) and all(_clean_num(x) is not None for x in _its)
    if not blocked and (ans.get("answer_type") in ("arithmetic", "count") or numeric):  # same deterministic V7 scale/format post-step
        from .tat_post import postprocess
        pp = postprocess(raw, q["question"], doc)
        p_answer, p_scale, src = pp["answer"], pp["scale"], "v7_infer_scale"
        sc_ok = any(d["check"] == "scale_vs_evidence" and d["verdict"] == "PASS" for d in D)
        if ans["scale"] and sc_ok and ans["scale"] != pp["scale"]:
            p_scale, src = ans["scale"], "model_structured_scale (gate scale check PASS)"
        elif not p_scale and ans.get("answer_type") != "count" and not _PCT_Q.search(q["question"]):
            u = _evidence_unit(ans["evidence"], doc)
            if u:
                p_scale, src = u, "evidence_unit (V7 inference empty)"
        D = D + [{"check": "scale_final", "verdict": "PASS", "reason": f"scale '{p_scale}' from {src}"}]
    p = {"answer": p_answer, "scale": p_scale, "expression": ans["expression"], "raw": raw, "evidence": ev,
         "confidence": conf01(ans.get("confidence")), "span_rules": []}
    tr = TQ.traceable(str(p["answer"]), ctx)
    det = 0.0 if blocked else TQ.tat_det(len(log), not reasons, tr, None)
    return {**p, "gate_passed": not reasons, "gate": log, "confidence_det": det, "route": r, "decisions": ctl.log, "calc_history": hist,
            "conf_formula": "tat_det (0.0 if v71 BLOCK)", "conf_inputs": {"gate_rounds": len(log), "gate_passed": not reasons, "traceable": tr, "rerank_p": None},
            "answer_type_pred": ans.get("answer_type"), "blocked": blocked,
            "v71": {"flag": "V71=1", "rounds": rounds, "final_gate": D, "blocked": blocked}}


def enabled() -> bool:
    return os.environ.get("V71") == "1"
