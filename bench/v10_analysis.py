"""V10 hard-set analysis (docs/V10_PREREG.md). Reuses bench/v9_gen_analysis.py unchanged (models fitted once on the 600
V9 design rows, applied frozen) and adds only what V10_PREREG section 4 declares on top of V9.1:
selective accuracy at 30% coverage, coverage at selective risk <= 20%, CRC at alpha 0.20 (design and cal re-fit),
paired AUROC diff V9_full - raw_answer_token_prob, and (hard_docfinqa only) AUROC / abstention split by
operands_in_context. Committed before any V10 full-run result was read.
Usage: python -m bench.v10_analysis <runs_dir> <design_glob> <oodsec_jsonl>"""
from __future__ import annotations
import json, math, sys
from . import v9_gen_analysis as G
from .v8_r2 import diff_ci
from .v9_final import score

SETS = ["hard_mhiertt", "hard_docfinqa"]
D = "docs/v10/hard"


def extra(name, rows, models, ds, dy, split, base):
    ids = [i for i in split["test_ids"] if i in rows]; cal = [i for i in split["cal_ids"] if i in rows]
    V = {i: score(rows[i], {"answer": rows[i]["output"]["answer"], "scale": rows[i]["output"]["scale"]}) for i in ids + cal}
    y = [int(V[i][2]) for i in ids]; yc = [int(V[i][2]) for i in cal]
    S = {i: G.scores(rows[i]["output"], models) for i in ids + cal}
    for k in G.ARMS:
        s = [S[i][k] for i in ids]; sc_ = [S[i][k] for i in cal]; m = base["signals"][k]
        m["selective_acc_cov30"] = G.sel_at_cov(y, s, .3)
        m["coverage_at_selective_risk_20pct"] = G.cov_at_risk(y, s, .20)
        lam_d = G.THRESHOLD if k == "lex_frozen" else G.crc_lambda(ds[k], dy, .20)
        lam_c = G.crc_lambda(sc_, yc, .20)
        for tag, lam in (("crc_design_lambda_a20", lam_d), ("crc_cal_refit_lambda_a20", lam_c)):
            a = [j for j, v in enumerate(s) if v >= lam]; w = sum(1 - y[j] for j in a)
            m[tag] = {"lambda": None if lam == math.inf else round(lam, 4), "realized_risk": round(w / len(y), 4),
                      "coverage": round(len(a) / len(y), 4), "risk_controlled": w / len(y) <= .20}
    base["paired_auroc_diff"]["V9_full - raw_answer_token_prob"] = {
        "item": diff_ci(y, [S[i]["raw_answer_token_prob"] for i in ids], [S[i]["V9_full"] for i in ids], G.AU)}
    if name == "hard_docfinqa":
        flag = {q["uid"]: (d.get("source") or {}).get("operands_in_context") for d in json.load(open(f"{D}/tatqa_dataset_{name}.json")) for q in d["questions"]}  # fix: flag lives on the document source
        lam = G.crc_lambda(ds["V9_full"], dy)
        st = {}
        for v in (True, False):
            ii = [j for j, i in enumerate(ids) if flag.get(i) is v]
            if not ii: continue
            yy = [y[j] for j in ii]
            st[str(v)] = {"n": len(ii), "semantic_acc": round(sum(yy) / len(ii), 4),
                          **{f"auroc_{k}": G.AU(yy, [S[ids[j]][k] for j in ii]) for k in ("V9_full", "lex_frozen", "raw_answer_token_prob")},
                          "abstain_rate_V9_full_design_crc": round(sum(1 for j in ii if S[ids[j]]["V9_full"] < lam) / len(ii), 4),
                          "abstain_rate_lex_frozen": round(sum(1 for j in ii if S[ids[j]]["lex_frozen"] < G.THRESHOLD) / len(ii), 4)}
        base["operands_in_context_strata"] = st
    return base


def main(runs, design_glob, oodsec):
    G.SETS = SETS
    G.DESIGN = design_glob
    models, ds, dy, oofa = G.design()
    res = {"design_oof_auroc": oofa, "sets": {}}
    for s in SETS:
        rows = G.load(f"{runs}/{s}_*.jsonl", "agent_v9"); rag = G.load(f"{runs}/{s}_*.jsonl", "rag")
        rows = {i: r for i, r in rows.items() if "v9" in r["output"]}
        if not rows: continue
        split = json.load(open(f"{D}/split_{s}.json"))
        g = {q["uid"]: d["table"]["uid"] for d in json.load(open(f"{D}/tatqa_dataset_{s}.json")) for q in d["questions"]}
        b = G.analyse(s, rows, rag, models, ds, dy, split, g)
        res["sets"][s] = extra(s, rows, models, ds, dy, split, b)
        res["sets"][s]["coverage_of_split"] = {"cal_rows": len(set(split["cal_ids"]) & set(rows)), "cal_ids": len(split["cal_ids"]),
                                               "test_rows": len(set(split["test_ids"]) & set(rows)), "test_ids": len(split["test_ids"])}
    # V10_PREREG section 5 decision rule for V9_full
    per = res["sets"]; k = "V9_full"
    lo = {s: per[s]["signals"][k]["auroc_ci_item"][0] for s in per}
    ci_hi = {s: per[s]["signals"][k]["auroc_ci_item"][1] for s in per}
    crc = {s: all(per[s]["signals"][k][t]["realized_risk"] <= a + .03 for t, a in (("crc_cal_refit_lambda", .10), ("crc_cal_refit_lambda_a20", .20))) for s in per}
    if per and all(lo[s] > .5 and crc[s] for s in per): lab = "HOLDS"
    elif per and all(lo[s] <= .5 <= ci_hi[s] for s in per): lab = "FAILS"
    else: lab = "PARTIAL"
    res["decision_V9_full"] = {"label": lab, "auroc_lower": lo, "cal_refit_crc_within_alpha+0.03": crc, "complete": len(per) == 2 and all(per[s]["coverage_of_split"]["cal_rows"] == per[s]["coverage_of_split"]["cal_ids"] and per[s]["coverage_of_split"]["test_rows"] == per[s]["coverage_of_split"]["test_ids"] for s in per)}
    return res


if __name__ == "__main__":
    print(json.dumps(main(*sys.argv[1:4]), indent=1, ensure_ascii=False, default=str))
