"""V8 paired report: python -m bench.v8_report <glob of jsonl> -> JSON. Arms v7/A/B/BC from the SAME agent_v8 rows.
Official TAT-QA EM/F1 (primary), semantic (secondary), fixed/broken + McNemar + bootstrap vs v7, cost/latency/calls per arm,
confidence: frozen V7 `lex` vs out-of-fold (5-fold CV on design) logistic on V8 features, both scored on the SAME target."""
from __future__ import annotations
import glob, json, math, random, sys
from pathlib import Path
from .heldout_report import auroc, aurc, ece, mcnemar, boot_ci
from .abstention import signal as lex, THRESHOLD
from .semantic import semantic_correct

DATA = Path(__file__).resolve().parent.parent / "data" / "bench" / "tatqa"
ARMS = ["v7", "A", "B", "BC"]
FEATS = ["agree", "ptr0_valid", "ptr0_agrees_vote", "v7_agrees_vote", "v7_gate_passed"]


def official(gold, pred):
    sys.path.insert(0, str(DATA))
    import tatqa_metric
    m = tatqa_metric.TaTQAEmAndF1()
    m(ground_truth=gold, prediction=pred.get("answer"), pred_scale=pred.get("scale") or "")
    e, f, _, _ = m.get_overall_metric()
    return e, f


def feats(o):
    f = o["v8"]["features"]
    return [float(f[k] or 0) for k in FEATS] + [lex(o)]


def logistic_fit(X, y, l2=1.0, it=3000, lr=0.1):
    import numpy as np
    X = np.asarray(X, float); y = np.asarray(y, float)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.c_[np.ones(len(X)), (X - mu) / sd]; w = np.zeros(Z.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-Z @ w)); g = Z.T @ (p - y) / len(y) + l2 * np.r_[0, w[1:]] / len(y); w -= lr * g * 10
    return lambda Xn: 1 / (1 + np.exp(-np.c_[np.ones(len(Xn)), (np.asarray(Xn, float) - mu) / sd] @ w)), w


def oof(X, y, k=5, seed=8008):
    idx = list(range(len(y))); random.Random(seed).shuffle(idx); out = [0.0] * len(y)
    for f in range(k):
        te = idx[f::k]; tr = [i for i in idx if i not in set(te)]
        pr, _ = logistic_fit([X[i] for i in tr], [y[i] for i in tr])
        for i, p in zip(te, pr([X[i] for i in te])):
            out[i] = float(p)
    return out


def boot_auroc_diff(y, s1, s2, B=2000, seed=2026):
    rng = random.Random(seed); n = len(y); d = []
    for _ in range(B):
        ix = [rng.randrange(n) for _ in range(n)]
        a, b = auroc([y[i] for i in ix], [s1[i] for i in ix]), auroc([y[i] for i in ix], [s2[i] for i in ix])
        if a is not None and b is not None:
            d.append(b - a)
    d.sort(); return [round(d[int(.025 * len(d))], 4), round(d[int(.975 * len(d)) - 1], 4)]


def conf(y, s, thr=None):
    o = {"auroc": None if auroc(y, s) is None else round(auroc(y, s), 4), "ece": round(ece(y, s), 4),
         "brier": round(sum((c - t) ** 2 for t, c in zip(y, s)) / len(y), 4), "aurc": round(aurc(y, s), 4)}
    if thr is not None:
        a = [t for t, c in zip(y, s) if c >= thr]
        o.update(threshold=round(thr, 4), coverage=round(len(a) / len(y), 4), selective_em=round(sum(a) / max(1, len(a)), 4))
    return o


def report(paths):
    rows = {}
    for p in paths:
        for l in open(p):
            r = json.loads(l)
            if r.get("system") == "agent_v8" and not r.get("error") and "v8" in (r.get("output") or {}):
                rows[r["id"]] = r
    ids = sorted(rows); n = len(ids)
    S = {a: {} for a in ARMS}
    for i in ids:
        r = rows[i]; g = r["gold"]; v = r["output"]["v8"]
        for a in ARMS:
            e, f = official(g, v[a])
            sem, _ = semantic_correct(v[a]["answer"], v[a].get("scale") or "", g.get("answer"), g.get("scale") or "", g.get("answer_type") or "")
            S[a][i] = (e, f, float(sem))
    tc = lambda r: r["meter"].get("trace_calls") or []
    tags = {"v7": lambda t: not t.startswith("v8"), "A": lambda t: not t.startswith("v8") or t.startswith("v8_ptr") and "sc" not in t and "repair" not in t,
            "B": lambda t: "repair" not in t, "BC": lambda t: True}
    out = {"n": n, "arms": {}}
    for a in ARMS:
        em = [S[a][i][0] for i in ids]
        cost = sum(c.get("cost_usd") or 0 for i in ids for c in tc(rows[i]) if tags[a](c["tag"]))
        lat = sum(c.get("latency_s") or 0 for i in ids for c in tc(rows[i]) if tags[a](c["tag"]))
        calls = sum(1 for i in ids for c in tc(rows[i]) if tags[a](c["tag"]))
        row = {"em": round(100 * sum(em) / n, 2), "f1": round(100 * sum(S[a][i][1] for i in ids) / n, 2),
               "sem": round(100 * sum(S[a][i][2] for i in ids) / n, 2), "calls_per_item": round(calls / n, 2),
               "latency_s_per_item": round(lat / n, 2), "cost_usd": round(cost, 4), "cost_per_correct": round(cost / max(1, sum(em)), 6)}
        if a != "v7":
            b = [S["v7"][i][0] for i in ids]
            p, fx, br = mcnemar([x >= .5 for x in b], [x >= .5 for x in em])
            d, lo, hi = boot_ci(b, em)
            row["vs_v7"] = {"fixed": fx, "broken": br, "delta_em": round(100 * d, 2), "ci95": [round(100 * lo, 2), round(100 * hi, 2)],
                            "mcnemar_p": round(p, 4), "accept": d > 0 and br <= fx / 3}
            bs = [S["v7"][i][2] for i in ids]
            ps, fs, bss = mcnemar([x >= .5 for x in bs], [S[a][i][2] >= .5 for i in ids])
            row["vs_v7_sem"] = {"fixed": fs, "broken": bss, "delta": round(100 * (sum(S[a][i][2] for i in ids) - sum(bs)) / n, 2)}
        out["arms"][a] = row
    # confidence, same target per comparison
    X = [feats(rows[i]["output"]) for i in ids]
    for a in ("v7", "BC", "B"):
        y = [int(S[a][i][0] >= .5) for i in ids]
        sl = [lex(rows[i]["output"]) for i in ids]
        so = oof(X, y)
        # design-fixed threshold for the logistic: keep the frozen lex coverage (same coverage => comparable selective EM)
        cov = sum(1 for s in sl if s >= THRESHOLD - 1e-9) / n
        thr = sorted(so, reverse=True)[max(0, int(round(cov * n)) - 1)]
        out[f"conf_target_{a}"] = {"lex_frozen": conf(y, [min(1, s) for s in sl], THRESHOLD), "v8_logistic_oof": conf(y, so, thr),
                                   "auroc_diff_ci95(v8-lex)": boot_auroc_diff(y, sl, so)}
    _, w = logistic_fit(X, [int(S["BC"][i][0] >= .5) for i in ids])
    out["logistic_weights_full_design(BC)"] = dict(zip(["bias"] + FEATS + ["lex"], [round(float(x), 3) for x in w]))
    out["pointer_valid_rate"] = round(sum(rows[i]["output"]["v8"]["features"]["ptr0_valid"] for i in ids) / n, 4)
    out["repair_rate"] = round(sum(1 for i in ids if rows[i]["output"]["v8"]["repair"]) / n, 4)
    return out, rows, S


if __name__ == "__main__":
    o, _, _ = report(sorted(glob.glob(sys.argv[1])))
    print(json.dumps(o, indent=1))
