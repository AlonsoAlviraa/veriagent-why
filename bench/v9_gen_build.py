"""V9.1 generalization sets (docs/V9_GEN_SETS.md). Built and fingerprinted BEFORE any model run on them.
Sets (TAT-QA JSON format, loaded with TATQA_SPLIT=<name>):
  gen_secq   SEC EDGAR XBRL 10-Q filings (filed 2026-07-01..2026-09-30, CIKs disjoint from oodsec); harder multi-step questions
             (margins, effective tax rate, current ratio, free cash flow, growth differences, implied prior-quarter values, cross
             table/text) with distractor columns (quarter vs year-to-date). Gold computed in Python from the DISPLAYED integers.
  gen_finqa  FinQA test split (Chen et al. 2021, MIT). Gold = FinQA's executed program value (exe_ans), kept only when it agrees
             with FinQA's stated answer string; numeric answers only.
  gen_jfinqa jfinqa v1 (2026, Apache-2.0, Japanese EDINET filings). Gold = re-execution of the dataset's own program at full
             precision, kept only when it rounds to the stated answer; numeric answers only.
Every set: <=400 questions, split by document (table) into calibration (25%) and test (75%) with a fixed seed; plus a disjoint
pilot pool (15 items, pipeline/feasibility check only, never used for analysis).
Usage: python -m bench.v9_gen_build <work dir with finqa_test.json, jfinqa_v1.json, cfq/, tenq_selected.txt>"""
from __future__ import annotations
import hashlib, json, math, random, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED, N_MAX, N_PILOT, CAL_FRAC = 20261025, 400, 15, 0.25
DS = ROOT / "data/bench/tatqa"
OUT = ROOT / "docs/v9/gen"


# ---------------- program execution (FinQA DSL; jfinqa uses the same DSL) ----------------
def _num(t, table):
    t = t.strip()
    if t.startswith("#"):
        return ("ref", int(t[1:]))
    if t.startswith("const_"):
        v = t[6:]
        return float(v.replace("m1", "-1")) if v != "m1" else -1.0
    return float(t.replace(",", "").replace("%", "")) if re.fullmatch(r"-?[\d,]*\.?\d+%?", t) else t


def execute(program, table=None):
    steps = program if isinstance(program, list) else [s.strip() + ")" for s in program.strip().rstrip(")").split("),")]
    res = []
    for s in steps:
        m = re.fullmatch(r"\s*(\w+)\((.*)\)\s*", s)
        if not m:
            raise ValueError(s)
        op, args = m.group(1), [a.strip() for a in m.group(2).split(",")]
        if op.startswith("table_"):
            row = next(r for r in table if r and r[0].strip().lower() == args[0].strip().lower())
            vals = [float(x) for x in (re.sub(r"[^\d.\-]", "", c.replace("(", "-")) for c in row[1:]) if x not in ("", "-", ".")]
            v = {"table_max": max, "table_min": min, "table_sum": sum, "table_average": lambda z: sum(z) / len(z)}[op](vals)
        else:
            a = [_num(x, table) for x in args]
            a = [res[x[1]] if isinstance(x, tuple) else x for x in a]
            if op == "add": v = a[0] + a[1]
            elif op == "subtract": v = a[0] - a[1]
            elif op == "multiply": v = a[0] * a[1]
            elif op == "divide": v = a[0] / a[1]
            elif op == "exp": v = a[0] ** a[1]
            elif op == "abs": v = abs(a[0])
            elif op in ("greater", "eq"): v = "yes" if (a[0] > a[1] if op == "greater" else a[0] == a[1]) else "no"
            else: raise ValueError(op)
        res.append(v)
    return res[-1]


def _split_groups(items, gkey, rng):
    groups = sorted({gkey(x) for x in items}); rng.shuffle(groups)
    ncal = max(1, round(CAL_FRAC * len(groups))); cal = set(groups[:ncal])
    return cal


def _write(name, docs, pilot_docs, meta):
    """docs: TAT-QA style list. Writes dataset (questions + pilot) and split file; returns summary."""
    rng = random.Random(SEED + 1)
    allq = [(d["table"]["uid"], q["uid"]) for d in docs for q in d["questions"]]
    cal = _split_groups(allq, lambda x: x[0], rng)
    cal_ids = [u for t, u in allq if t in cal]; test_ids = [u for t, u in allq if t not in cal]
    pilot_ids = [q["uid"] for d in pilot_docs for q in d["questions"]]
    assert not set(pilot_ids) & {u for _, u in allq}
    path = DS / f"tatqa_dataset_{name}.json"
    path.write_text(json.dumps(docs + pilot_docs, ensure_ascii=False, indent=0))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"tatqa_dataset_{name}.json").write_text(path.read_text())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    split = {"name": f"v9gen_{name}", "tatqa_split": name, "seed": SEED, "dataset_sha256": sha, **meta,
             "ids": cal_ids + test_ids, "cal_ids": cal_ids, "test_ids": test_ids, "pilot_ids": pilot_ids}
    sp = OUT / f"split_{name}.json"; sp.write_text(json.dumps(split, ensure_ascii=False, indent=0))
    for part in ("pilot",):
        (OUT / f"split_{name}_pilot.json").write_text(json.dumps({"name": f"v9gen_{name}_pilot", "tatqa_split": name,
                                                               "dataset_sha256": sha, "ids": pilot_ids}, indent=0))
    return {"n": len(allq), "n_cal": len(cal_ids), "n_test": len(test_ids), "n_tables": len({t for t, _ in allq}),
            "n_pilot": len(pilot_ids), "dataset_sha256": sha, "split_sha256": hashlib.sha256(sp.read_bytes()).hexdigest()}


def _close(a, b, tol=0.005):
    return abs(a - b) <= max(0.011, tol * abs(b))


# ---------------- FinQA ----------------
def build_finqa(work: Path):
    data = json.load(open(work / "finqa_test.json"))
    keep, drop = [], {"non_numeric": 0, "program_error": 0, "disagree": 0}
    for x in data:
        qa = x["qa"]; ans = qa["answer"].strip().replace("$", "").replace(",", "").strip()
        if not re.fullmatch(r"-?\d*\.?\d+%?", ans):
            drop["non_numeric"] += 1; continue
        try:
            v = execute(qa["program"], x["table"])
        except Exception:
            drop["program_error"] += 1; continue
        if isinstance(v, str) or not _close(float(qa["exe_ans"]), v):
            drop["program_error"] += 1; continue
        stated = float(ans.rstrip("%")); pct = ans.endswith("%")
        if pct and _close(v * 100, stated, 0.01):
            gold, scale = round(v * 100, 4), "percent"
        elif _close(v, stated, 0.01):
            gold, scale = round(v, 4), ("percent" if pct else "")
        else:
            drop["disagree"] += 1; continue
        keep.append((x, gold, scale))
    rng = random.Random(SEED); rng.shuffle(keep)
    def doc(x, gold, scale):
        uid = "genfinqa-" + hashlib.sha256(x["id"].encode()).hexdigest()[:16]
        paras = [{"uid": f"{uid}-p{i}", "order": i + 1, "text": t} for i, t in enumerate(x["pre_text"] + x["post_text"]) if t.strip() not in ("", ".")]
        return {"table": {"uid": "genfinqa-t-" + x["filename"], "table": x["table"]}, "paragraphs": paras,
                "questions": [{"uid": uid, "order": 1, "question": x["qa"]["question"], "answer": gold, "derivation": x["qa"]["program"],
                               "answer_type": "arithmetic", "answer_from": "table-text", "rel_paragraphs": [], "req_comparison": False,
                               "scale": scale}], "source": {"finqa_id": x["id"], "filename": x["filename"], "stated_answer": x["qa"]["answer"]}}
    # one doc per FinQA filename group may hold several questions; the table uid is the filename so clustering is by filing page
    main, pilot, seen_pilot_files = [], [], set()
    for x, g, s in keep:
        if len(pilot) < N_PILOT:
            pilot.append(doc(x, g, s)); seen_pilot_files.add(x["filename"]); continue
        if x["filename"] in seen_pilot_files: continue
        if len(main) < N_MAX: main.append(doc(x, g, s))
    for d in pilot: d["table"]["uid"] += "-pilot"
    return _write("gen_finqa", main, pilot, {"source": "FinQA test (github czyssrs/FinQA, MIT)", "filter": drop, "eligible": len(keep)})


# ---------------- jfinqa ----------------
def build_jfinqa(work: Path):
    data = json.load(open(work / "jfinqa_v1.json"))
    keep, drop = [], {"non_numeric": 0, "program_error": 0, "disagree": 0}
    for x in data:
        a = x["qa"]["answer"].strip()
        m = re.fullmatch(r"(-?[\d,]*\.?\d+)(%|ポイント|百万円|倍|円)?", a)
        if not m:
            drop["non_numeric"] += 1; continue
        try:
            v = execute(x["qa"]["program"])
        except Exception:
            drop["program_error"] += 1; continue
        if isinstance(v, str):
            drop["non_numeric"] += 1; continue
        stated = float(m.group(1).replace(",", "")); dec = len(m.group(1).split(".")[1]) if "." in m.group(1) else 0
        if abs(round(v, dec) - stated) > 10 ** -dec * 0.51 and not _close(v, stated, 0.01):
            drop["disagree"] += 1; continue
        unit = m.group(2) or ""
        scale = "percent" if unit in ("%", "ポイント") else ("million" if unit == "百万円" or (not unit and abs(v) >= 1000) else "")
        keep.append((x, round(v, 4), scale))
    rng = random.Random(SEED); rng.shuffle(keep)
    def doc(x, gold, scale):
        uid = "genjfinqa-" + hashlib.sha256(x["id"].encode()).hexdigest()[:16]
        t = x["table"]; rows = [t["headers"]] + t["rows"]
        paras = [{"uid": f"{uid}-p{i}", "order": i + 1, "text": s} for i, s in enumerate(x["pre_text"] + x["post_text"] + [f"単位：{x['scale']}"])]
        return {"table": {"uid": "genjfinqa-t-" + x["source_doc_id"], "table": rows}, "paragraphs": paras,
                "questions": [{"uid": uid, "order": 1, "question": x["qa"]["question"], "answer": gold, "derivation": " | ".join(x["qa"]["program"]),
                               "answer_type": "arithmetic", "answer_from": "table-text", "rel_paragraphs": [], "req_comparison": False,
                               "scale": scale}], "source": {"jfinqa_id": x["id"], "edinet_code": x["edinet_code"], "doc": x["source_doc_id"],
                                                             "stated_answer": x["qa"]["answer"], "subtask": x["subtask"]}}
    main, pilot, pf = [], [], set()
    for x, g, s in keep:
        if len(pilot) < N_PILOT:
            pilot.append(doc(x, g, s)); pf.add(x["source_doc_id"]); continue
        if x["source_doc_id"] in pf: continue
        if len(main) < N_MAX: main.append(doc(x, g, s))
    for d in pilot: d["table"]["uid"] += "-pilot"
    return _write("gen_jfinqa", main, pilot, {"source": "jfinqa v1 (huggingface ajtgjmdjp/jfinqa, Apache-2.0)", "filter": drop, "eligible": len(keep)})




# ---------------- SEC 10-Q multi-step (programmatic) ----------------
ISC = [("Revenue", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]),
       ("Cost of revenue", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]),
       ("Gross profit", ["GrossProfit"]),
       ("Research and development", ["ResearchAndDevelopmentExpense"]),
       ("Selling, general and administrative", ["SellingGeneralAndAdministrativeExpense"]),
       ("Operating income (loss)", ["OperatingIncomeLoss"]),
       ("Income (loss) before income taxes", ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                                              "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"]),
       ("Income tax expense (benefit)", ["IncomeTaxExpenseBenefit"]),
       ("Net income (loss)", ["NetIncomeLoss"])]
BSC = [("cash and cash equivalents", ["CashAndCashEquivalentsAtCarryingValue"]), ("total current assets", ["AssetsCurrent"]),
       ("total current liabilities", ["LiabilitiesCurrent"]), ("total assets", ["Assets"]), ("total liabilities", ["Liabilities"]),
       ("total stockholders' equity", ["StockholdersEquity"])]
CFC = [("net cash provided by (used in) operating activities", ["NetCashProvidedByUsedInOperatingActivities"]),
       ("capital expenditures", ["PaymentsToAcquirePropertyPlantAndEquipment"])]


def _dd(s): return date.fromisoformat(s)


def _facts(cf, concepts, accn):
    g = cf.get("facts", {}).get("us-gaap", {})
    for c in concepts:
        u = [f for f in g.get(c, {}).get("units", {}).get("USD", []) if f.get("accn") == accn]
        if u:
            return u
    return []


def _dur(fs, end, lo, hi):
    for f in fs:
        if f.get("start") and f["end"] == end and lo <= (_dd(f["end"]) - _dd(f["start"])).days <= hi:
            return f["val"], (_dd(f["end"]) - _dd(f["start"])).days
    return None, None


def _secq_doc(cf, cik, filed, accn):
    rev = _facts(cf, ISC[0][1], accn)
    qs = sorted({f["end"] for f in rev if f.get("start") and 80 <= (_dd(f["end"]) - _dd(f["start"])).days <= 100})
    if not qs: return None
    cur = qs[-1]; prevs = [e for e in qs if 350 <= (_dd(cur) - _dd(e)).days <= 380]
    if not prevs: return None
    prev = prevs[0]
    _, ylen = _dur(rev, cur, 170, 290)
    if not ylen: return None
    months = 6 if ylen < 230 else 9
    cols = {}
    for lab, cs in ISC:
        fs = _facts(cf, cs, accn)
        v = [_dur(fs, cur, 80, 100)[0], _dur(fs, prev, 80, 100)[0], _dur(fs, cur, 170, 290)[0], _dur(fs, prev, 170, 290)[0]]
        if all(x is not None for x in v):
            cols[lab] = [round(x / 1e3) for x in v]
    if "Revenue" not in cols or min(abs(x) for x in cols["Revenue"]) < 1000 or len(cols) < 5: return None
    bs = {}
    ae = sorted({f["end"] for f in _facts(cf, ["Assets"], accn) if not f.get("start") and f["end"] < cur})
    if not ae: return None
    fye = ae[-1]  # prior balance-sheet date = latest Assets instant before period end (fiscal year end)
    for lab, cs in BSC:
        fs = [f for f in _facts(cf, cs, accn) if not f.get("start")]
        a = next((f["val"] for f in fs if f["end"] == cur), None)
        b = next((f["val"] for f in fs if f["end"] == fye), None)
        if a is not None and b is not None:
            bs[lab] = (round(a / 1e3), round(b / 1e3), fye)
    cfl = {}
    for lab, cs in CFC:
        fs = _facts(cf, cs, accn)
        a, b = _dur(fs, cur, 170, 290)[0], _dur(fs, prev, 170, 290)[0]
        if a is not None and b is not None: cfl[lab] = (round(a / 1e3), round(b / 1e3))
    if len(bs) < 3 or not cfl: return None
    return {"cik": cik, "accn": accn, "filed": filed, "cur": cur, "prev": prev, "months": months, "name": cf.get("entityName", str(cik)),
            "is": cols, "bs": bs, "cf": cfl}


def _secq_questions(D):
    I, B, C, m, cur, prev = D["is"], D["bs"], D["cf"], D["months"], D["cur"], D["prev"]
    q3, ytd = f"the three months ended {cur}", f"the {m} months ended {cur}"
    out = []
    def add(frm, q, v, sc):
        if v is not None and math.isfinite(v) and round(v, 2) != 0: out.append((frm, q, round(v, 2), sc))
    R = I["Revenue"]
    gp = I.get("Gross profit") or ([r - c for r, c in zip(R, I["Cost of revenue"])] if "Cost of revenue" in I else None)
    if gp:
        add("table", f"What was the gross margin (gross profit as a percentage of revenue) for {q3}?", gp[0] / R[0] * 100, "percent")
        add("table", f"By how many percentage points did the gross margin change in the three months ended {cur} compared with the three months ended {prev}?",
            gp[0] / R[0] * 100 - gp[1] / R[1] * 100, "percent")
    if "Operating income (loss)" in I:
        add("table", f"What was the operating margin for {ytd}?", I["Operating income (loss)"][2] / R[2] * 100, "percent")
    t, p = I.get("Income tax expense (benefit)"), I.get("Income (loss) before income taxes")
    if t and p and p[0] > 0:
        add("table", f"What was the effective income tax rate for {q3}?", t[0] / p[0] * 100, "percent")
    add("table", f"What was the difference, in percentage points, between year-over-year revenue growth for the three-month period and for the {m}-month period ended {cur}?",
        (R[0] - R[1]) / abs(R[1]) * 100 - (R[2] - R[3]) / abs(R[3]) * 100, "percent")
    add("table", f"What was the revenue for the {m} months ended {cur} excluding the three months ended {cur}?", R[2] - R[0], "thousand")
    for lab in ("Research and development", "Selling, general and administrative"):
        if lab in I:
            add("table", f"By how many percentage points did {lab.lower()} expense as a percentage of revenue change in the three months ended {cur} versus the prior-year quarter?",
                I[lab][0] / R[0] * 100 - I[lab][1] / R[1] * 100, "percent")
    if "Net income (loss)" in I and I["Net income (loss)"][3] != 0:
        n = I["Net income (loss)"]; add("table", f"What was the percentage change in net income (loss) for the {m} months ended {cur} compared with the prior-year period?",
                                        (n[2] - n[3]) / abs(n[3]) * 100, "percent")
    ca, cl = B.get("total current assets"), B.get("total current liabilities")
    if ca and cl and cl[0] > 0 and cl[1] > 0:
        add("text", f"What was the current ratio as of {cur}?", ca[0] / cl[0], "")
        add("text", f"By how much did the current ratio change between {ca[2]} and {cur}?", ca[0] / cl[0] - ca[1] / cl[1], "")
    li, eq = B.get("total liabilities"), B.get("total stockholders' equity")
    if li and eq and eq[0] > 0:
        add("text", f"What was the ratio of total liabilities to total stockholders' equity as of {cur}?", li[0] / eq[0], "")
    o, k = C.get(CFC[0][0]), C.get(CFC[1][0])
    if o and k:
        add("text", f"What was free cash flow (operating cash flow minus capital expenditures) for {ytd}?", o[0] - k[0], "thousand")
        add("table-text", f"What was free cash flow as a percentage of revenue for {ytd}?", (o[0] - k[0]) / R[2] * 100, "percent")
    if B.get("cash and cash equivalents"):
        c = B["cash and cash equivalents"]; add("table-text", f"What was cash and cash equivalents as of {cur} as a multiple of revenue for {q3}?", c[0] / R[0], "")
    if o:
        add("table-text", f"What was operating cash flow as a percentage of net income (loss) for {ytd}?",
            o[0] / I["Net income (loss)"][2] * 100 if "Net income (loss)" in I and I["Net income (loss)"][2] != 0 else None, "percent")
    return out


def build_secq(work: Path):
    rows = [l.split() for l in open(work / "tenq_selected.txt")]
    docs = []
    for cik, filed, path in rows:
        cik = int(cik); accn = path.rsplit("/", 1)[1].removesuffix(".txt"); p = work / f"cfq/{cik:010d}.json"
        if not p.exists(): continue
        try: cf = json.load(open(p))
        except Exception: continue
        D = _secq_doc(cf, cik, filed, accn)
        if D: docs.append(D)
    rng = random.Random(SEED); rng.shuffle(docs)
    fmt = lambda x: f"({abs(x):,})" if x < 0 else f"{x:,}"
    main, pilot, n = [], [], 0
    for D in docs:
        cands = _secq_questions(D)
        if len(cands) < 4: continue
        by = {}
        for c in cands: by.setdefault(c[0], []).append(c)
        pick = [rng.choice(by[k]) for k in ("table", "text", "table-text") if k in by]
        rest = [c for c in cands if c not in pick]; rng.shuffle(rest); pick = (pick + rest)[:4]
        m, cur, prev = D["months"], D["cur"], D["prev"]
        table = [["(In thousands)", f"Three months ended {cur}", f"Three months ended {prev}", f"{m} months ended {cur}", f"{m} months ended {prev}"]] + \
                [[lab] + [fmt(x) for x in v] for lab, v in D["is"].items()]
        bsl = list(D["bs"].items())
        paras = [{"uid": f"p0-{D['accn']}", "order": 1, "text": f"{D['name']} filed its quarterly report on Form 10-Q on {D['filed']} for the quarter ended {cur}. Amounts in the table and below are in thousands of US dollars; parentheses denote negative amounts."},
                 {"uid": f"p1-{D['accn']}", "order": 2, "text": "Balance sheet: " + "; ".join(f"{lab} were ${fmt(a)} thousand as of {cur} and ${fmt(b)} thousand as of {fy}" for lab, (a, b, fy) in bsl) + "."},
                 {"uid": f"p2-{D['accn']}", "order": 3, "text": f"Cash flows: for the {m} months ended {cur}, " + "; ".join(f"{lab} was ${fmt(a)} thousand, compared with ${fmt(b)} thousand for the {m} months ended {prev}" for lab, (a, b) in D["cf"].items()) + "."}]
        qs = []
        for j, (frm, q, ans, sc) in enumerate(pick):
            uid = "gensecq-" + hashlib.sha256(f"{D['accn']}|{q}".encode()).hexdigest()[:16]
            qs.append({"uid": uid, "order": j + 1, "question": q, "answer": ans, "derivation": "programmatic (bench.v9_gen_build._secq_questions)",
                       "answer_type": "arithmetic", "answer_from": frm, "rel_paragraphs": [], "req_comparison": False, "scale": sc})
        doc = {"table": {"uid": "gensecq-t-" + D["accn"], "table": table}, "paragraphs": paras, "questions": qs,
               "source": {"cik": D["cik"], "accession": D["accn"], "filed": D["filed"], "entity": D["name"], "period_end": cur, "prior_period_end": prev}}
        if len(pilot) < 4: pilot.append(doc); continue
        if n + len(qs) > N_MAX: break
        main.append(doc); n += len(qs)
    for d in pilot: d["table"]["uid"] += "-pilot"
    return _write("gen_secq", main, pilot, {"source": "SEC EDGAR XBRL companyfacts, 10-Q filed 2026 Q3 (Jul-Sep), CIKs disjoint from oodsec",
                                            "docs_eligible": len(docs)})


if __name__ == "__main__":
    w = Path(sys.argv[1]); which = sys.argv[2:] or ["secq", "finqa", "jfinqa"]
    print(json.dumps({k: globals()[f"build_{k}"](w) for k in which}, indent=1, ensure_ascii=False))
