"""V9 analysis, frozen before any design result (docs/V9_PREREG.md).
Usage: python -m bench.v9_report '<glob of agent_v9 jsonl>' [--v7 '<glob of V7 rows on the same ids>']
Folds: GroupKFold by TAT-QA table (k=5, seed 9009) -- Code Reviewer's V8 note. Bootstrap: 2000 item resamples, seed 2026."""
from __future__ import annotations
import glob, json, math, random, sys
from pathlib import Path
from .heldout_report import auroc, aurc, ece, mcnemar, boot_ci
from .abstention import signal as lex, THRESHOLD
from .semantic import semantic_correct
from .v8_report import official, logistic_fit, conf, FEATS as V8F
from .v8_r2 import diff_ci

ROOT = Path(__file__).resolve().parent.parent
SEED, ALPHA = 9009, 0.10  # conformal risk control target: P(answered AND wrong) <= ALPHA
I1 = ["ans_mean_lp", "ans_min_lp", "seq_mean_lp", "ans_min_margin"]
I2 = ["ptrue", "verbal"]
I3 = ["v7_share", "sem_entropy", "sample_agree_v7"]


def table_of() -> dict:
    tr = json.load(open(ROOT / "data/bench/tatqa/tatqa_dataset_train.json"))
    return {q["uid"]: d["table"]["uid"] for d in tr for q in d["questions"]}


def gfolds(ids, k=5, seed=SEED):
    t = table_of(); groups = sorted({t[i] for i in ids}); random.Random(seed).shuffle(groups)
    g2f = {g: j % k for j, g in enumerate(groups)}
    return [[n for n, i in enumerate(ids) if g2f[t[i]] == f] for f in range(k)]


def oof(X, y, fo):
    out = [0.0] * len(y)
    for te in fo:
        st = set(te); tr = [i for i in range(len(y)) if i not in st]
        g, _ = logistic_fit([X[i] for i in tr], [y[i] for i in tr])
        for i, p in zip(te, g([X[i] for i in te])):
            out[i] = float(p)
    return out


def crc(score, y, fo, alpha=ALPHA):
    """Conformal risk control (Angelopoulos et al. 2024; used for abstention by Yadkori et al. 2024): per fold, the smallest
    threshold whose calibrated loss (n R + 1)/(n+1) <= alpha, loss = answered AND wrong (monotone in the threshold)."""
    ans = wrong = 0; n = len(y)
    for te in fo:
        st = set(te); cal = [i for i in range(n) if i not in st]; m = len(cal)
        cands = sorted({score[i] for i in cal}) + [math.inf]
        lam = next(l for l in cands if (sum(1 for i in cal if score[i] >= l and not y[i]) + 1) / (m + 1) <= alpha)
        for i in te:
            if score[i] >= lam:
                ans += 1; wrong += 1 - y[i]
    return {"alpha": alpha, "realized_risk_answered_and_wrong": round(wrong / n, 4), "coverage": round(ans / n, 4),
            "selective_em": round((ans - wrong) / max(1, ans), 4)}


def f(o, names):
    v = o["v9"]["features"]
    return [float(v.get(k)) if v.get(k) is not None else 0.0 for k in names]


def v8f(o):
    v = o["v9"].get("v8_features") or {}
    return [float(v.get(k) or 0) for k in V8F]


def load(pattern, system):
    rows = {}
    for p in sorted(glob.glob(pattern)):
        for l in open(p):
            r = json.loads(l)
            if r.get("system") == system and not r.get("error"):
                rows[r["id"]] = r
    return rows


def cost(rows, ids, pred):
    tc = [c for i in ids for c in (rows[i]["meter"].get("trace_calls") or []) if pred(c["tag"])]
    n = len(ids)
    return {"calls_per_item": round(len(tc) / n, 2), "sec_per_item": round(sum(c.get("latency_s") or 0 for c in tc) / n, 2),
            "tokens_per_item": round(sum((c.get("prompt_tokens") or 0) + (c.get("completion_tokens") or 0) for c in tc) / n, 1),
            "cost_usd": round(sum(c.get("cost_usd") or 0 for c in tc), 4)}


def report(pattern):
    rows = load(pattern, "agent_v9")
    ids = sorted(i for i in rows if "v9" in rows[i]["output"]); n = len(ids)
    O = {i: rows[i]["output"] for i in ids}
    def score(i, ans):
        g = rows[i]["gold"]; e, f1 = official(g, ans)
        s, _ = semantic_correct(ans["answer"], ans.get("scale") or "", g.get("answer"), g.get("scale") or "", g.get("answer_type") or "")
        return e, f1, float(s)
    V7 = {i: score(i, {"answer": O[i]["answer"], "scale": O[i]["scale"]}) for i in ids}
    out = {"n": n, "n_tables": len({table_of()[i] for i in ids})}
    out["v7"] = {"em": round(100 * sum(V7[i][0] for i in ids) / n, 2), "f1": round(100 * sum(V7[i][1] for i in ids) / n, 2),
                 "sem": round(100 * sum(V7[i][2] for i in ids) / n, 2), **cost(rows, ids, lambda t: not t.startswith(("v8", "v9")))}
    # I3b answer arm
    I3b = {i: score(i, O[i]["v9"]["I3b"]) if "I3b" in O[i]["v9"] else V7[i] for i in ids}
    a, b = [V7[i][0] >= .5 for i in ids], [I3b[i][0] >= .5 for i in ids]
    p, fx, br = mcnemar(a, b); d, lo, hi = boot_ci([V7[i][0] for i in ids], [I3b[i][0] for i in ids])
    out["I3b_answer_arm"] = {"em": round(100 * sum(I3b[i][0] for i in ids) / n, 2), "f1": round(100 * sum(I3b[i][1] for i in ids) / n, 2),
                             "changed": sum(1 for i in ids if O[i]["v9"].get("I3b_changed")), "fixed": fx, "broken": br,
                             "delta_em": round(100 * d, 2), "ci95": [round(100 * lo, 2), round(100 * hi, 2)], "mcnemar_p": round(p, 4),
                             "accept(dEM>0 and broken<=fixed/3)": bool(d > 0 and br <= fx / 3),
                             **cost(rows, ids, lambda t: not t.startswith("v8"))}
    # confidence (target: V7 EM)
    y = [int(V7[i][0] >= .5) for i in ids]; fo = gfolds(ids)
    L = [[lex(O[i])] for i in ids]
    S = {"lex_frozen": [min(1.0, x[0]) for x in L],
         "lex_platt": oof(L, y, fo),
         "I1_msp_raw": [O[i]["v9"]["features"].get("ans_msp") or 0.0 for i in ids],
         "I2_ptrue_raw": [O[i]["v9"]["features"].get("ptrue") if O[i]["v9"]["features"].get("ptrue") is not None else 0.5 for i in ids],
         "I2_verbal_raw": [O[i]["v9"]["features"].get("verbal") if O[i]["v9"]["features"].get("verbal") is not None else 0.5 for i in ids],
         "I3_v7share_raw": [O[i]["v9"]["features"].get("v7_share", 0.0) for i in ids],
         "V8_refit": oof([v8f(O[i]) + [lex(O[i])] for i in ids], y, fo),
         "V9_cheap": oof([[lex(O[i])] + f(O[i], I1 + I2) for i in ids], y, fo),
         "V9_full": oof([[lex(O[i])] + f(O[i], I1 + I2 + I3) + v8f(O[i]) for i in ids], y, fo)}
    cov = sum(1 for s in S["lex_frozen"] if s >= THRESHOLD - 1e-9) / n
    out["conf"] = {}
    for k, s in S.items():
        thr = THRESHOLD if k == "lex_frozen" else sorted(s, reverse=True)[max(0, int(round(cov * n)) - 1)]
        out["conf"][k] = conf(y, s, thr)
    E = lambda yy, ss: -ece(yy, ss)
    tests = {"H1 V9_cheap vs lex_platt": ("lex_platt", "V9_cheap"), "H2 V9_full vs V8_refit": ("V8_refit", "V9_full"),
             "s: V9_cheap vs V8_refit": ("V8_refit", "V9_cheap"), "s: V9_full vs lex_platt": ("lex_platt", "V9_full"),
             "s: I1_msp_raw vs lex_frozen": ("lex_frozen", "I1_msp_raw"), "s: I2_ptrue_raw vs lex_frozen": ("lex_frozen", "I2_ptrue_raw"),
             "s: I3_v7share_raw vs lex_frozen": ("lex_frozen", "I3_v7share_raw")}
    out["tests"] = {}
    for name, (s1, s2) in tests.items():
        dA = diff_ci(y, S[s1], S[s2], lambda yy, ss: auroc(yy, ss) or 0.5)
        dE = diff_ci(y, S[s1], S[s2], E)
        out["tests"][name] = {"auroc_diff_ci95": dA, "neg_ece_diff_ci95": dE,
                              "auroc_improves": dA[0] > 0, "ece_improves": dE[0] > 0}
    out["I4_conformal"] = {k: crc(S[k], y, fo) for k in ("lex_platt", "V8_refit", "V9_cheap", "V9_full")}
    out["cost"] = {"V7/I1 (0 extra)": out["v7"]["calls_per_item"],
                   "V9_cheap (+P(True))": cost(rows, ids, lambda t: not t.startswith(("v8", "v9_sc"))),
                   "V8_refit (+pointer)": cost(rows, ids, lambda t: not t.startswith("v9")),
                   "V9_full (all)": cost(rows, ids, lambda t: True)}
    out["diag"] = {"lp_ok_rate": round(sum(1 for i in ids if O[i]["v9"]["features"].get("lp_ok")) / n, 4),
                   "ptrue_src": {s: sum(1 for i in ids if O[i]["v9"]["features"].get("ptrue_src") == s) for s in ("lp", "verdict", None)}}
    return out


if __name__ == "__main__":
    print(json.dumps(report(sys.argv[1]), indent=1))
