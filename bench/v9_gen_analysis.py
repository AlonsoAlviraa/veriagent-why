"""V9.1 generalization analysis (docs/V9_1_PREREG.md). Written and committed BEFORE any full run on the new sets.
Nothing is selected on the new sets. Models are fitted ONCE on the 600 V9 design rows (labels = official TAT-QA EM, as in
bench.v9_final) and applied frozen. Primary correctness label on the new sets = semantic_correct (bench.semantic);
official EM is reported as a sensitivity label. Metrics are computed on each set's TEST ids; the CAL ids are used only by the
declared 'CRC re-fit on new-set calibration split' variant.
Usage: python -m bench.v9_gen_analysis <runs_dir> <design_glob> <oodsec_jsonl>"""
from __future__ import annotations
import json, math, random, sys
from pathlib import Path
from .heldout_report import auroc, aurc, ece
from .abstention import signal as lex, THRESHOLD
from .v8_report import logistic_fit, conf
from .v8_r2 import diff_ci
from .v9_report import I1, I2, I3, f, v8f, load, cost, ALPHA, gfolds, oof
from .v9_final import score, crc_lambda, cluster_ci

SETS = ["gen_secq", "gen_jfinqa", "gen_finqa"]
FITTED = {"lex_platt": lambda O: [lex(O)], "V8_refit": lambda O: v8f(O) + [lex(O)],
          "V9_cheap": lambda O: [lex(O)] + f(O, I1 + I2), "V9_full": lambda O: [lex(O)] + f(O, I1 + I2 + I3) + v8f(O),
          "abl_logprobs_only": lambda O: f(O, I1), "abl_ptrue_only": lambda O: f(O, ["ptrue"]),
          "abl_semantic_entropy_only": lambda O: f(O, ["sem_entropy"])}
RAW = {"lex_frozen": lambda O: min(1.0, lex(O)), "raw_answer_token_prob": lambda O: O["v9"]["features"].get("ans_msp") or 0.0,
       "raw_ptrue": lambda O: O["v9"]["features"].get("ptrue") if O["v9"]["features"].get("ptrue") is not None else 0.5}
ARMS = list(RAW) + list(FITTED)
AU = lambda y, s: auroc(y, s) or 0.5


def auroc_ci(y, s, groups=None, B=2000, seed=2026):
    rng = random.Random(seed); n = len(y); v = []
    if groups is None:
        for _ in range(B):
            ix = [rng.randrange(n) for _ in range(n)]; v.append(AU([y[i] for i in ix], [s[i] for i in ix]))
    else:
        G = sorted(set(groups)); by = {g: [i for i, x in enumerate(groups) if x == g] for g in G}
        for _ in range(B):
            ix = [i for g in (rng.choice(G) for _ in G) for i in by[g]]; v.append(AU([y[i] for i in ix], [s[i] for i in ix]))
    v.sort(); return [round(v[int(.025 * B)], 4), round(v[int(.975 * B) - 1], 4)]


def sel_at_cov(y, s, c):
    k = max(1, int(round(c * len(y)))); o = sorted(range(len(y)), key=lambda i: -s[i])[:k]
    return round(sum(y[i] for i in o) / k, 4)


def cov_at_risk(y, s, r=0.10):
    o = sorted(range(len(y)), key=lambda i: -s[i]); best = 0.0; ok = 0
    for k, i in enumerate(o, 1):
        ok += y[i]
        if 1 - ok / k <= r: best = k / len(y)
    return round(best, 4)


def kendall(a, b):
    ks = [k for k in a if k in b]; c = d = 0
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            x = (a[ks[i]] - a[ks[j]]) * (b[ks[i]] - b[ks[j]]); c += x > 0; d += x < 0
    return round((c - d) / max(1, c + d), 4)


def design():
    D = load(DESIGN, "agent_v9"); did = sorted(i for i in D if "v9" in D[i]["output"]); DO = {i: D[i]["output"] for i in did}
    dy = [int(score(D[i], {"answer": DO[i]["answer"], "scale": DO[i]["scale"]})[0] >= .5) for i in did]
    models, ds, oofa = {}, {}, {}
    fo = gfolds(did)
    for k, fx in FITTED.items():
        X = [fx(DO[i]) for i in did]; g, _ = logistic_fit(X, dy); models[k] = g
        ds[k] = [float(v) for v in g(X)]; oofa[k] = round(AU(dy, oof(X, dy, fo)), 4)
    for k, fx in RAW.items():
        ds[k] = [fx(DO[i]) for i in did]; oofa[k] = round(AU(dy, ds[k]), 4)
    return models, ds, dy, oofa


def scores(O, models):
    S = {k: fx(O) for k, fx in RAW.items()}
    for k, g in models.items(): S[k] = float(g([FITTED[k](O)])[0])
    return S


def analyse(name, rows, rag, models, ds, dy, split, groups_of):
    ids = [i for i in split["test_ids"] if i in rows]; cal = [i for i in split["cal_ids"] if i in rows]
    out = {"n_test": len(ids), "n_cal": len(cal), "missing_test": len(split["test_ids"]) - len(ids)}
    V = {i: score(rows[i], {"answer": rows[i]["output"]["answer"], "scale": rows[i]["output"]["scale"]}) for i in ids + cal}
    ans = {}
    for sysn, R in (("V7_agent", rows), ("plain_RAG", rag)):
        ii = [i for i in ids if i in R]
        if not ii: continue
        sc = [score(R[i], {"answer": R[i]["output"].get("answer"), "scale": R[i]["output"].get("scale")}) for i in ii]
        ans[sysn] = {"n": len(ii), "em": round(100 * sum(x[0] for x in sc) / len(ii), 2), "f1": round(100 * sum(x[1] for x in sc) / len(ii), 2),
                     "semantic": round(100 * sum(x[2] for x in sc) / len(ii), 2), "errors_semantic": sum(1 for x in sc if not x[2])}
    out["answers"] = ans
    out["n_errors_primary"] = sum(1 for i in ids if not V[i][2])
    y = [int(V[i][2]) for i in ids]; yem = [int(V[i][0] >= .5) for i in ids]; yc = [int(V[i][2]) for i in cal]
    groups = [groups_of[i] for i in ids]
    S = {i: scores(rows[i]["output"], models) for i in ids + cal}
    out["signals"] = {}
    for k in ARMS:
        s = [S[i][k] for i in ids]; sc_ = [S[i][k] for i in cal]
        m = conf(y, s); m["auroc_ci_item"] = auroc_ci(y, s); m["auroc_ci_table"] = auroc_ci(y, s, groups)
        m["auroc_official_em_label"] = round(AU(yem, s), 4)
        m["selective_acc_cov50"] = sel_at_cov(y, s, .5); m["selective_acc_cov80"] = sel_at_cov(y, s, .8)
        m["coverage_at_selective_risk_10pct"] = cov_at_risk(y, s, .10)
        lam_d = THRESHOLD if k == "lex_frozen" else crc_lambda(ds[k], dy)
        lam_c = crc_lambda(sc_, yc)
        for tag, lam in (("crc_design_lambda", lam_d), ("crc_cal_refit_lambda", lam_c)):
            a = [j for j, v in enumerate(s) if v >= lam]; w = sum(1 - y[j] for j in a)
            m[tag] = {"lambda": None if lam == math.inf else round(lam, 4), "realized_risk": round(w / len(y), 4),
                      "coverage": round(len(a) / len(y), 4), "selective_acc": round((len(a) - w) / max(1, len(a)), 4),
                      "risk_controlled": w / len(y) <= ALPHA}
        out["signals"][k] = m
    out["paired_auroc_diff"] = {}
    for base in ("lex_frozen", "V9_cheap"):
        for k in ARMS:
            if k == base: continue
            out["paired_auroc_diff"][f"{k} - {base}"] = {"item": diff_ci(y, [S[i][base] for i in ids], [S[i][k] for i in ids], AU),
                                                        "table": cluster_ci(y, [S[i][base] for i in ids], [S[i][k] for i in ids], groups, AU)}
    out["cost"] = {"V7": cost(rows, ids, lambda t: not t.startswith(("v8", "v9"))),
                   "V9_cheap": cost(rows, ids, lambda t: not t.startswith(("v8", "v9_sc"))),
                   "V8_refit": cost(rows, ids, lambda t: not t.startswith("v9")), "V9_full": cost(rows, ids, lambda t: True)}
    out["lp_ok_rate"] = round(sum(1 for i in ids if rows[i]["output"]["v9"]["features"].get("lp_ok")) / len(ids), 4)
    return out


def verdict(oofa, per):
    """Pre-registered rule (docs/V9_1_PREREG.md section 5)."""
    v = {}
    for k in ARMS:
        a = [per[s]["signals"][k]["auroc"] or .5 for s in per]; lo = [per[s]["signals"][k]["auroc_ci_item"][0] for s in per]
        drop = oofa[k] - sum(a) / len(a)
        crc_ok = all(per[s]["signals"][k]["crc_design_lambda"]["realized_risk"] <= ALPHA + .02 for s in per)
        n_chance = sum(1 for x in lo if x <= .5)
        if all(x > .5 for x in lo) and drop <= .05 and crc_ok: lab = "GENERALIZES"
        elif drop >= .10 or n_chance >= 2: lab = "OVERFIT / DOES NOT TRANSFER"
        else: lab = "PARTIAL"
        v[k] = {"design_auroc": oofa[k], "mean_new_auroc": round(sum(a) / len(a), 4), "drop": round(drop, 4),
                "n_sets_auroc_ci_includes_0.5": n_chance, "design_crc_within_alpha+0.02_all_sets": crc_ok, "label": lab}
    gen = [k for k in v if v[k]["label"] == "GENERALIZES"]
    best = max(gen, key=lambda k: v[k]["mean_new_auroc"]) if gen else None
    return v, best


def main(runs, design_glob, oodsec):
    global DESIGN; DESIGN = design_glob
    models, ds, dy, oofa = design()
    res = {"design_oof_auroc": oofa, "sets": {}}
    O = load(oodsec, "agent_v9"); oid = sorted(i for i in O if "v9" in O[i]["output"])
    oy = [int(score(O[i], {"answer": O[i]["output"]["answer"], "scale": O[i]["output"]["scale"]})[2]) for i in oid]
    res["oodsec_reference_auroc"] = {k: round(AU(oy, [scores(O[i]["output"], models)[k] for i in oid]), 4) for k in ARMS}
    for s in SETS:
        rows = load(f"{runs}/{s}_v9*.jsonl", "agent_v9"); rag = load(f"{runs}/{s}_rag*.jsonl", "rag")
        if not rows: continue
        split = json.load(open(f"docs/v9/gen/split_{s}.json"))
        g = {q["uid"]: d["table"]["uid"] for d in json.load(open(f"docs/v9/gen/tatqa_dataset_{s}.json")) for q in d["questions"]}
        res["sets"][s] = analyse(s, rows, rag, models, ds, dy, split, g)
    per = res["sets"]
    res["stability"] = {k: {"design_oof": oofa[k], "oodsec": res["oodsec_reference_auroc"][k], **{s: per[s]["signals"][k]["auroc"] for s in per}} for k in ARMS}
    res["kendall_tau_vs_design"] = {s: kendall(oofa, {k: per[s]["signals"][k]["auroc"] or .5 for k in ARMS}) for s in per}
    res["kendall_tau_vs_design"]["oodsec"] = kendall(oofa, res["oodsec_reference_auroc"])
    if per: res["verdict"], res["best_generalizing_signal"] = verdict(oofa, per)
    return res


if __name__ == "__main__":
    print(json.dumps(main(*sys.argv[1:4]), indent=1, ensure_ascii=False))
