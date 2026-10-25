"""Export the frozen V9_full confidence model for the app (app/v9_full_model.json).
Refits EXACTLY as bench.v9_final does (bench.v8_report.logistic_fit on all V9 design rows, same features) and
stores mu/sd/w plus the CRC threshold (alpha=ALPHA, loss = answered AND wrong) calibrated on the same rows.
Usage: python -m bench.export_v9_full '<design glob>' ['<holdout glob>' to print a reproduction check]"""
from __future__ import annotations
import glob, hashlib, json, sys
import numpy as np
from .v8_report import logistic_fit
from .v9_final import feats, score, crc_lambda
from .v9_report import load, I1, I2, I3, V8F, ALPHA
from .heldout_report import auroc


def rows(pattern):
    D = load(pattern, "agent_v9"); ids = sorted(i for i in D if "v9" in D[i]["output"]); O = {i: D[i]["output"] for i in ids}
    y = [int(score(D[i], {"answer": O[i]["answer"], "scale": O[i]["scale"]})[0] >= .5) for i in ids]
    return [feats(O[i])["V9_full"] for i in ids], y


def main(design, hold=None):
    X, y = rows(design)
    g, w = logistic_fit(X, y)
    A = np.asarray(X, float); mu, sd = A.mean(0), A.std(0) + 1e-9
    s = [float(v) for v in g(X)]
    model = {"name": "V9_full", "features": ["lex"] + I1 + I2 + I3 + ["v8:" + k for k in V8F], "mu": mu.tolist(), "sd": sd.tolist(),
             "w": [float(v) for v in w], "n_design": len(y), "design_accuracy": round(sum(y) / len(y), 4),
             "crc": {"alpha": ALPHA, "lambda": crc_lambda(s, y, ALPHA)}, "fit": "bench.v8_report.logistic_fit (l2=1, 3000 it)",
             "design_files_sha256": hashlib.sha256(b"".join(open(p, "rb").read() for p in sorted(glob.glob(design)))).hexdigest()}
    if hold:
        Xh, yh = rows(hold)
        model["holdout_check"] = {"n": len(yh), "auroc": round(auroc(yh, [float(v) for v in g(Xh)]), 4)}
    json.dump(model, open("app/v9_full_model.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in model.items() if k not in ("mu", "sd", "w")}, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
