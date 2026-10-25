"""V8 hold-out report (single pre-registered run). Applies FROZEN configs (bench/calib/v8_conf*.json) with no refit;
baselines: frozen lex@0.809, lex Platt / isotonic fitted on the design rows, raw agreement. Target = V7 official EM.
Usage: python -m bench.v8_holdout '<holdout glob>' '<design glob>'"""
import glob, json, math, sys
from .v8_r2 import feats_k, isotonic_fit, diff_ci
from .v8_report import report, logistic_fit, conf
from .abstention import signal as lex, THRESHOLD
from .heldout_report import auroc, aurc, ece


def apply(cfg, x):
    z = cfg["w"][0] + sum(w * (v - m) / s for w, v, m, s in zip(cfg["w"][1:], x, cfg["mu"], cfg["sd"]))
    return 1 / (1 + math.exp(-z))


def main(hold, design):
    o, rows, S = report(sorted(glob.glob(hold)))
    _, drows, dS = report(sorted(glob.glob(design)))
    ids = sorted(rows); y = [int(S["v7"][i][0] >= .5) for i in ids]; O = [rows[i]["output"] for i in ids]
    did = sorted(drows); dy = [int(dS["v7"][i][0] >= .5) for i in did]; dl = [lex(drows[i]["output"]) for i in did]
    platt, _ = logistic_fit([[v] for v in dl], dy); iso = isotonic_fit(dl, dy)
    sl = [lex(x) for x in O]
    sig = {"lex_frozen": ([min(1.0, s) for s in sl], THRESHOLD), "lex_platt_design": ([float(p) for p in platt([[s] for s in sl])], None),
           "lex_isotonic_design": ([iso(s) for s in sl], None), "agree_raw": ([x["v8"]["features"]["agree"] for x in O], None)}
    for name, path, k in (("v8_k5_primary", "bench/calib/v8_conf.json", 5), ("v8_k0_secondary", "bench/calib/v8_conf_k0.json", 0)):
        cfg = json.load(open(path)); sig[name] = ([apply(cfg, feats_k(x, k)) for x in O], cfg["threshold"])
    out = {"n": len(ids), "answers": o["arms"], "repair_rate": o["repair_rate"], "signals": {}, "pointer_valid_rate": o["pointer_valid_rate"]}
    for nm, (s, thr) in sig.items():
        out["signals"][nm] = conf(y, s, thr)
    au = lambda a, b: auroc(a, b) or 0.5
    for nm in ("v8_k5_primary", "v8_k0_secondary"):
        for b in ("lex_frozen", "lex_platt_design", "lex_isotonic_design", "agree_raw"):
            out[f"{nm}_vs_{b}"] = {"d_auroc_ci95": diff_ci(y, sig[b][0], sig[nm][0], au), "d_aurc_ci95": diff_ci(y, sig[b][0], sig[nm][0], aurc),
                                   "d_ece_ci95": diff_ci(y, sig[b][0], sig[nm][0], ece)}
    return out


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], sys.argv[2]), indent=1))
