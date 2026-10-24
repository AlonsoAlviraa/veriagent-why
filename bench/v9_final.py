"""V9 final hold-out analysis on the OOD set 'oodsec' (docs/V9_FINAL_SET.md, amendment in docs/V9_PREREG.md).
Written and committed BEFORE the hold-out run. Nothing is fitted on hold-out rows:
  * lex_frozen: abstention.signal at the frozen 0.809 threshold.
  * lex_platt, V8_refit, V9_cheap, V9_full: logistic models (bench.v8_report.logistic_fit, same features as bench.v9_report)
    fitted ONCE on all 600 V9 design rows, applied to hold-out rows.
  * I4 conformal risk control: threshold calibrated on the 600 design rows (alpha=0.10, loss = answered AND wrong), applied as-is.
  * Coverage-matched selective EM at frozen-lex hold-out coverage (as in v9_report).
  * Bootstrap: 2000 item resamples, seed 2026 (pre-registered); table-cluster bootstrap reported as a declared sensitivity check.
Usage: python -m bench.v9_final '<holdout glob>' '<design glob>'"""
from __future__ import annotations
import glob, json, math, random, sys
from .heldout_report import auroc, aurc, ece, mcnemar, boot_ci
from .abstention import signal as lex, THRESHOLD
from .semantic import semantic_correct
from .v8_report import official, logistic_fit, conf
from .v8_r2 import diff_ci
from .v9_report import I1, I2, I3, f, v8f, load, cost, ALPHA


def feats(O):
    return {"lex_platt": [lex(O)], "V8_refit": v8f(O) + [lex(O)], "V9_cheap": [lex(O)] + f(O, I1 + I2),
            "V9_full": [lex(O)] + f(O, I1 + I2 + I3) + v8f(O)}


def score(r, ans):
    g = r["gold"]; e, f1 = official(g, ans)
    s, _ = semantic_correct(ans["answer"], ans.get("scale") or "", g.get("answer"), g.get("scale") or "", g.get("answer_type") or "")
    return e, f1, float(s)


def crc_lambda(s, y, alpha=ALPHA):
    m = len(y); cands = sorted(set(s)) + [math.inf]
    return next(l for l in cands if (sum(1 for a, t in zip(s, y) if a >= l and not t) + 1) / (m + 1) <= alpha)


def cluster_ci(y, s1, s2, groups, fn, B=2000, seed=2026):
    rng = random.Random(seed); G = sorted(set(groups)); by = {g: [i for i, x in enumerate(groups) if x == g] for g in G}; d = []
    for _ in range(B):
        ix = [i for g in (rng.choice(G) for _ in G) for i in by[g]]
        d.append(fn([y[i] for i in ix], [s2[i] for i in ix]) - fn([y[i] for i in ix], [s1[i] for i in ix]))
    d.sort(); return [round(d[int(.025 * B)], 4), round(d[int(.975 * B) - 1], 4)]


def main(hold, design):
    H, D = load(hold, "agent_v9"), load(design, "agent_v9")
    hid = sorted(i for i in H if "v9" in H[i]["output"]); did = sorted(i for i in D if "v9" in D[i]["output"])
    HO, DO = {i: H[i]["output"] for i in hid}, {i: D[i]["output"] for i in did}
    HV = {i: score(H[i], {"answer": HO[i]["answer"], "scale": HO[i]["scale"]}) for i in hid}
    DV = {i: score(D[i], {"answer": DO[i]["answer"], "scale": DO[i]["scale"]}) for i in did}
    y = [int(HV[i][0] >= .5) for i in hid]; dy = [int(DV[i][0] >= .5) for i in did]; n = len(hid)
    tab = {q["uid"]: d["table"]["uid"] for d in json.load(open("data/bench/tatqa/tatqa_dataset_oodsec.json")) for q in d["questions"]}
    groups = [tab[i] for i in hid]
    out = {"n": n, "n_design_fit": len(did), "n_tables": len(set(groups)),
           "v7": {"em": round(100 * sum(HV[i][0] for i in hid) / n, 2), "f1": round(100 * sum(HV[i][1] for i in hid) / n, 2),
                  "sem": round(100 * sum(HV[i][2] for i in hid) / n, 2)}}
    I3b = {i: score(H[i], HO[i]["v9"]["I3b"]) if "I3b" in HO[i]["v9"] else HV[i] for i in hid}
    a, b = [HV[i][0] >= .5 for i in hid], [I3b[i][0] >= .5 for i in hid]
    p, fx, br = mcnemar(a, b); dd, lo, hi = boot_ci([HV[i][0] for i in hid], [I3b[i][0] for i in hid])
    out["I3b_answer_arm_reported_only"] = {"em": round(100 * sum(I3b[i][0] for i in hid) / n, 2), "fixed": fx, "broken": br,
                                           "delta_em": round(100 * dd, 2), "ci95": [round(100 * lo, 2), round(100 * hi, 2)], "mcnemar_p": round(p, 4)}
    S = {"lex_frozen": [min(1.0, lex(HO[i])) for i in hid],
         "I1_msp_raw": [HO[i]["v9"]["features"].get("ans_msp") or 0.0 for i in hid],
         "I2_ptrue_raw": [HO[i]["v9"]["features"].get("ptrue") if HO[i]["v9"]["features"].get("ptrue") is not None else 0.5 for i in hid]}
    DS = {}
    for k in ("lex_platt", "V8_refit", "V9_cheap", "V9_full"):
        g, _ = logistic_fit([feats(DO[i])[k] for i in did], dy)
        S[k] = [float(v) for v in g([feats(HO[i])[k] for i in hid])]
        DS[k] = [float(v) for v in g([feats(DO[i])[k] for i in did])]
    cov = sum(1 for s in S["lex_frozen"] if s >= THRESHOLD - 1e-9) / n
    out["lex_frozen_coverage"] = round(cov, 4)
    out["conf"] = {}
    for k, s in S.items():
        thr = THRESHOLD if k == "lex_frozen" else sorted(s, reverse=True)[max(0, int(round(cov * n)) - 1)]
        out["conf"][k] = conf(y, s, thr)
    E = lambda yy, ss: -ece(yy, ss); AU = lambda yy, ss: auroc(yy, ss) or 0.5; AR = lambda yy, ss: -aurc(yy, ss)
    tests = {"P1 V9_cheap vs lex_frozen (primary, amended)": ("lex_frozen", "V9_cheap"),
             "P2 V9_full vs V8_refit (primary)": ("V8_refit", "V9_full"),
             "P1-orig V9_cheap vs lex_platt (original H1, reported)": ("lex_platt", "V9_cheap"),
             "s: V9_cheap vs V8_refit": ("V8_refit", "V9_cheap"), "s: V9_full vs lex_frozen": ("lex_frozen", "V9_full")}
    out["tests"] = {}
    for name, (s1, s2) in tests.items():
        out["tests"][name] = {"auroc_diff_ci95": diff_ci(y, S[s1], S[s2], AU), "neg_ece_diff_ci95": diff_ci(y, S[s1], S[s2], E),
                              "neg_aurc_diff_ci95": diff_ci(y, S[s1], S[s2], AR),
                              "auroc_diff_ci95_table_cluster": cluster_ci(y, S[s1], S[s2], groups, AU)}
        t = out["tests"][name]; t["auroc_improves"] = t["auroc_diff_ci95"][0] > 0; t["ece_improves"] = t["neg_ece_diff_ci95"][0] > 0
    out["I4_conformal_design_threshold"] = {}
    for k in ("lex_platt", "V8_refit", "V9_cheap", "V9_full"):
        lam = crc_lambda(DS[k], dy); ans = [i for i, s in enumerate(S[k]) if s >= lam]; wrong = sum(1 - y[i] for i in ans)
        out["I4_conformal_design_threshold"][k] = {"alpha": ALPHA, "lambda": round(lam, 4), "realized_risk_answered_and_wrong": round(wrong / n, 4),
                                                   "coverage": round(len(ans) / n, 4), "selective_em": round((len(ans) - wrong) / max(1, len(ans)), 4),
                                                   "risk_controlled": wrong / n <= ALPHA}
    out["cost"] = {"V7": cost(H, hid, lambda t: not t.startswith(("v8", "v9"))),
                   "V9_cheap": cost(H, hid, lambda t: not t.startswith(("v8", "v9_sc"))),
                   "V8_refit": cost(H, hid, lambda t: not t.startswith("v9")), "V9_full": cost(H, hid, lambda t: True)}
    out["by_type"] = {}
    for i, r in zip(hid, y):
        k = H[i]["gold"]["answer_type"] + "/" + H[i]["gold"]["answer_from"]
        e = out["by_type"].setdefault(k, [0, 0]); e[0] += 1; e[1] += r
    out["diag"] = {"lp_ok_rate": round(sum(1 for i in hid if HO[i]["v9"]["features"].get("lp_ok")) / n, 4)}
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], sys.argv[2]), indent=1))
