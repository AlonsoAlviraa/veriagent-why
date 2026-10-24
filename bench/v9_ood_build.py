"""V9 final out-of-distribution test set 'oodsec' (docs/V9_FINAL_SET.md). Built BEFORE any model run on it.
Source: SEC EDGAR XBRL companyfacts (US public-domain government data) for 10-K filings FILED 2026-06-01..2026-10-24, i.e. after
the model's documented post-training cutoff (May 2026). Facts are taken only from the filing's own accession number.
Gold answers are computed in Python from the numbers DISPLAYED in the table/text (millions, integer); no LLM is involved.
Paragraphs are deterministic templates (declared): the 'text' part of the hybrid context is templated, not filing prose.
Usage: python -m bench.v9_ood_build <companyfacts cache dir>  -> data/bench/tatqa/tatqa_dataset_oodsec.json, docs/v9/ood/*"""
from __future__ import annotations
import hashlib, json, random, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED, PER_DOC, N_MAX = 20261024, 4, 400
TABLE_C = [  # (label, us-gaap concepts in priority order)
    ("Revenue", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]),
    ("Cost of revenue", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]),
    ("Gross profit", ["GrossProfit"]),
    ("Research and development expense", ["ResearchAndDevelopmentExpense"]),
    ("Selling, general and administrative expense", ["SellingGeneralAndAdministrativeExpense"]),
    ("Operating income", ["OperatingIncomeLoss"]),
    ("Income tax expense", ["IncomeTaxExpenseBenefit"]),
    ("Net income", ["NetIncomeLoss"]),
]
TEXT_C = [
    ("net cash provided by operating activities", ["NetCashProvidedByUsedInOperatingActivities"]),
    ("capital expenditures", ["PaymentsToAcquirePropertyPlantAndEquipment"]),
    ("depreciation and amortization", ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"]),
    ("interest expense", ["InterestExpense", "InterestExpenseNonoperating"]),
    ("share-based compensation expense", ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"]),
]


def d(s): return date.fromisoformat(s)


def annual(cf, concepts, accn):
    """{period_end: value_usd} for ~1-year durations reported in this accession (first concept that has >=2 years)."""
    g = cf.get("facts", {}).get("us-gaap", {})
    for c in concepts:
        u = g.get(c, {}).get("units", {}).get("USD", [])
        v = {}
        for f in u:
            if f.get("accn") == accn and f.get("start") and 350 <= (d(f["end"]) - d(f["start"])).days <= 380:
                v.setdefault(f["end"], f["val"])
        if len(v) >= 2:
            return c, v
    return None, {}


def fmt(x): return f"{x:,}"


def build(cache: Path):
    rows = [l.split() for l in open(ROOT / "docs/v9/ood/edgar_10k_filed_2026-06-01_to_2026-10-24.txt")]
    docs, seen = [], set()
    for p in rows:
        cik, filed, path = int(p[-3]), p[-2], p[-1]
        accn = path.rsplit("/", 1)[1].removesuffix(".txt")
        if cik in seen or not (cache / f"{cik:010d}.json").exists():
            continue
        try:
            cf = json.load(open(cache / f"{cik:010d}.json"))
        except Exception:
            continue
        rev_c, rev = annual(cf, TABLE_C[0][1], accn)
        if not rev:
            continue
        cur = max(rev); prev = [e for e in rev if 350 <= (d(cur) - d(e)).days <= 380]
        if not prev or d(cur).year == d(prev[0]).year:
            continue
        prev = prev[0]; cy, py = str(d(cur).year), str(d(prev).year)

        def pair(concepts):
            c, v = annual(cf, concepts, accn)
            if cur in v and prev in v:
                a, b = round(v[cur] / 1e6), round(v[prev] / 1e6)
                if abs(a) >= 10 and abs(b) >= 10:
                    return c, a, b
            return None
        tab = [(lab, *x) for lab, cs in TABLE_C if (x := pair(cs))]
        txt = [(lab, *x) for lab, cs in TABLE_C[:0] + TEXT_C if (x := pair(cs))]
        if len(tab) < 3 or len(txt) < 1 or tab[0][0] != "Revenue" or tab[0][2] < 100:
            continue
        seen.add(cik)
        name = cf.get("entityName", str(cik))
        table = [["(In millions)", f"Fiscal {cy}", f"Fiscal {py}"]] + [[lab, fmt(a), fmt(b)] for lab, _, a, b in tab]
        paras = [{"uid": f"p0-{accn}", "order": 1, "text": f"{name} filed its annual report on Form 10-K on {filed} for the fiscal year ended {cur}. "
                                                           f"The comparative fiscal year ended {prev}. Amounts are in US dollars."}]
        for k, (lab, _, a, b) in enumerate(txt):
            paras.append({"uid": f"p{k+1}-{accn}", "order": k + 2,
                          "text": f"In fiscal {cy}, {lab} was ${fmt(a)} million, compared with ${fmt(b)} million in fiscal {py}."})
        docs.append({"cik": cik, "accn": accn, "filed": filed, "cur": cur, "prev": prev, "cy": cy, "py": py, "name": name,
                     "tab": tab, "txt": txt, "table": table, "paras": paras,
                     "concepts": {lab: c for lab, c, _, _ in tab + txt}})
    rng = random.Random(SEED)
    rng.shuffle(docs)
    out, n = [], 0
    for D in docs:
        if n >= N_MAX:
            break
        cy, py = D["cy"], D["py"]
        cands = []
        for lab, _, a, b in D["tab"]:
            L = lab[0].lower() + lab[1:]
            cands += [("span", "table", f"What was the {L} in fiscal {cy}?", [fmt(a)], "million", [lab, fmt(a)]),
                      ("arithmetic", "table", f"What was the change in {L} between fiscal {py} and fiscal {cy}?", round(a - b, 2), "million", [lab]),
                      ("arithmetic", "table", f"What was the percentage change in {L} from fiscal {py} to fiscal {cy}?",
                       round((a - b) / abs(b) * 100, 2), "percent", [lab]),
                      ("arithmetic", "table", f"What was the average {L} for fiscal {py} and fiscal {cy}?", round((a + b) / 2, 2), "million", [lab])]
        for lab, _, a, b in D["txt"]:
            cands += [("span", "text", f"What was the {lab} in fiscal {cy}?", [fmt(a)], "million", [lab]),
                      ("arithmetic", "text", f"What was the change in {lab} between fiscal {py} and fiscal {cy}?", round(a - b, 2), "million", [lab])]
            r = D["tab"][0]  # revenue
            cands.append(("arithmetic", "table-text", f"What was {lab} as a percentage of revenue in fiscal {cy}?",
                          round(a / r[2] * 100, 2), "percent", [lab, "Revenue"]))
        cands = [c for c in cands if c[3] != 0]  # official TAT-QA scorer cannot score a gold of 0 (found by oracle self-check)
        by = {}
        for c in cands:
            by.setdefault(c[1], []).append(c)
        pick = [rng.choice(by[k]) for k in ("table", "text", "table-text") if k in by]
        rest = [c for c in cands if c not in pick]; rng.shuffle(rest)
        pick = (pick + rest)[:PER_DOC]
        qs = []
        for j, (typ, frm, q, ans, sc, deriv) in enumerate(pick):
            uid = "oodsec-" + hashlib.sha256(f"{D['accn']}|{q}".encode()).hexdigest()[:16]
            qs.append({"uid": uid, "order": j + 1, "question": q, "answer": ans, "derivation": " | ".join(map(str, deriv)),
                       "answer_type": typ, "answer_from": frm, "rel_paragraphs": [], "req_comparison": False, "scale": sc})
        n += len(qs)
        out.append({"table": {"uid": "oodsec-t-" + D["accn"], "table": D["table"]}, "paragraphs": D["paras"], "questions": qs,
                    "source": {"cik": D["cik"], "accession": D["accn"], "filed": D["filed"], "entity": D["name"],
                               "period_end": D["cur"], "prior_period_end": D["prev"], "concepts": D["concepts"]}})
    ds = ROOT / "data/bench/tatqa/tatqa_dataset_oodsec.json"
    ds.write_text(json.dumps(out, indent=0))
    (ROOT / "docs/v9/ood/tatqa_dataset_oodsec.json").write_text(ds.read_text())
    ids = [q["uid"] for x in out for q in x["questions"]]
    split = {"name": "v9_final_oodsec", "tatqa_split": "oodsec", "seed": SEED,
             "source": "SEC EDGAR XBRL companyfacts, 10-K filed 2026-06-01..2026-10-24, programmatic gold; see docs/V9_FINAL_SET.md",
             "dataset_sha256": hashlib.sha256(ds.read_bytes()).hexdigest(), "ids": ids}
    sp = ROOT / "docs/v9/final_oodsec.json"
    sp.write_text(json.dumps(split, indent=0))
    return {"docs_eligible": len(docs), "docs_used": len(out), "n_questions": len(ids), "dataset_sha256": split["dataset_sha256"],
            "split_sha256": hashlib.sha256(sp.read_bytes()).hexdigest()}


if __name__ == "__main__":
    print(json.dumps(build(Path(sys.argv[1])), indent=1))
