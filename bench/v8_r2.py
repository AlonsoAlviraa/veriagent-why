"""V8 round 2 (offline, no new LLM calls): k-truncated features from logged samples, fair recalibrated-lex baselines
(Platt + isotonic) on the SAME 5 folds as the V8 logistic, and the 'checker' feature (share of samples agreeing with V7).
Answer is always V7's; target = V7 official EM. Usage: python -m bench.v8_r2 '<glob>'"""
from __future__ import annotations
import glob, json, random, sys
from collections import Counter
from .v8 import key
from .v8_report import report, logistic_fit, conf, boot_auroc_diff
from .abstention import signal as lex, THRESHOLD
from .heldout_report import ece

BASE = ["agree", "ptr0_valid", "ptr0_agrees_vote", "v7_agrees_vote", "v7_gate_passed", "lex"]
CHECK = ["v7_support"]


def feats_k(o: dict, k: int, checker: bool = False) -> list[float]:
    """Pointer-0 (T=0) + the FIRST k of the logged T=0.7 samples (deterministic truncation)."""
    v = o["v8"]; sm = v["samples"][:1 + k]; e0 = sm[0]["exec"]
    val = [s for s in sm if s["exec"]["ok"]]
    votes = Counter(key(s["exec"]["answer"]) for s in val)
    pick = None
    if votes:
        nt = votes.most_common(1)[0][1]; tied = [a for a, c in votes.items() if c == nt]
        pick = key(e0["answer"]) if e0["ok"] and key(e0["answer"]) in tied else votes.most_common(1)[0][0]
    v7k = key(v["v7"]["answer"])
    f = [votes[pick] / len(sm) if pick else 0.0, float(e0["ok"]), float(bool(e0["ok"] and key(e0["answer"]) == pick)),
         float(pick is not None and pick == v7k), float(bool(v["features"]["v7_gate_passed"])), lex(o)]
    if checker:
        f.append(sum(1 for s in val if key(s["exec"]["answer"]) == v7k) / len(sm))
    return f


def folds(n, k=5, seed=8008):
    idx = list(range(n)); random.Random(seed).shuffle(idx)
    return [idx[f::k] for f in range(k)]


def isotonic_fit(x, y):
    pts = sorted(zip(x, y)); blocks = []  # PAV, increasing
    for xi, yi in pts:
        blocks.append([xi, xi, yi, 1])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] >= blocks[-1][2] / blocks[-1][3]:
            b = blocks.pop(); blocks[-1][1] = b[1]; blocks[-1][2] += b[2]; blocks[-1][3] += b[3]
    def f(z):
        for lo, hi, s, c in blocks:
            if z <= hi:
                return s / c
        return blocks[-1][2] / blocks[-1][3]
    return f


def oof(X, y, method="logistic"):
    out = [0.0] * len(y)
    for te in folds(len(y)):
        st = set(te); tr = [i for i in range(len(y)) if i not in st]
        if method == "isotonic":
            f = isotonic_fit([X[i][0] for i in tr], [y[i] for i in tr]); pr = [f(X[i][0]) for i in te]
        else:
            g, _ = logistic_fit([X[i] for i in tr], [y[i] for i in tr]); pr = g([X[i] for i in te])
        for i, p in zip(te, pr):
            out[i] = float(p)
    return out


def diff_ci(y, s1, s2, fn, B=2000, seed=2026):
    rng = random.Random(seed); n = len(y); d = []
    for _ in range(B):
        ix = [rng.randrange(n) for _ in range(n)]
        d.append(fn([y[i] for i in ix], [s2[i] for i in ix]) - fn([y[i] for i in ix], [s1[i] for i in ix]))
    d.sort(); return [round(d[int(.025 * B)], 4), round(d[int(.975 * B) - 1], 4)]


def run(paths):
    _, rows, S = report(paths)
    ids = sorted(rows); y = [int(S["v7"][i][0] >= .5) for i in ids]; o = [rows[i]["output"] for i in ids]
    sl = [lex(x) for x in o]; n = len(y)
    cov = sum(1 for s in sl if s >= THRESHOLD - 1e-9) / n
    thr_at = lambda s: sorted(s, reverse=True)[max(0, int(round(cov * n)) - 1)]
    sig = {"lex_frozen": [min(1.0, s) for s in sl], "lex_platt_oof": oof([[s] for s in sl], y), "lex_isotonic_oof": oof([[s] for s in sl], y, "isotonic")}
    for k in (2, 5):
        sig[f"v8_k{k}_oof"] = oof([feats_k(x, k) for x in o], y)
        sig[f"v8_k{k}_checker_oof"] = oof([feats_k(x, k, True) for x in o], y)
    out = {"n": n, "v7_em": round(sum(y) / n, 4), "coverage_target(lex@0.809)": round(cov, 4), "signals": {}}
    for name, s in sig.items():
        out["signals"][name] = conf(y, s, THRESHOLD if name == "lex_frozen" else thr_at(s))
    au = lambda yy, ss: __import__("bench.heldout_report", fromlist=["auroc"]).auroc(yy, ss) or 0.5
    for k in ("v8_k2_oof", "v8_k5_oof", "v8_k2_checker_oof"):
        for b in ("lex_platt_oof", "lex_isotonic_oof"):
            out[f"{k}_vs_{b}"] = {"d_auroc_ci95": diff_ci(y, sig[b], sig[k], au), "d_ece_ci95": diff_ci(y, sig[b], sig[k], ece)}
    out["v8_k2_checker_vs_v8_k2"] = {"d_auroc_ci95": diff_ci(y, sig["v8_k2_oof"], sig["v8_k2_checker_oof"], au)}
    out["_cost_note"] = "k=2 uses 1+2 pointer calls/item on top of V7 (vs 1+5)"
    return out, rows, S, sig, ids, y


if __name__ == "__main__":
    print(json.dumps(run(sorted(glob.glob(sys.argv[1])))[0], indent=1))
