"""Generates bench/calib/v8_conf.json: logistic refit on the full design slice (production features, k=5, target V7 EM);
threshold = the OOF score cut that matches frozen-lex@0.809 coverage, applied to the refit. Prints sha256[:16].
Usage: python -m bench.v8_freeze '<glob of round-1 jsonl>'"""
import glob, hashlib, json, sys
import numpy as np
from .v8_r2 import feats_k, oof, BASE
from .v8_report import report, logistic_fit
from .abstention import signal as lex, THRESHOLD


def main(pattern, out="bench/calib/v8_conf.json", K=5):
    _, rows, S = report(sorted(glob.glob(pattern)))
    ids = sorted(rows); y = [int(S["v7"][i][0] >= .5) for i in ids]
    X = [feats_k(rows[i]["output"], K) for i in ids]; n = len(ids)
    cov = sum(1 for i in ids if lex(rows[i]["output"]) >= THRESHOLD - 1e-9) / n
    so = oof(X, y); thr = float(sorted(so, reverse=True)[int(round(cov * n)) - 1])
    _, w = logistic_fit(X, y); Xa = np.asarray(X, float)
    cfg = {"name": "v8_candidate_conf", "answer": "V7 unchanged (agent_markov)", "confidence": "logistic on pointer-SC features, target=V7 EM",
           "features": BASE, "mu": Xa.mean(0).round(6).tolist(), "sd": (Xa.std(0) + 1e-9).round(6).tolist(), "w": [round(float(x), 6) for x in w],
           "threshold": round(thr, 6), "threshold_rule": "OOF (5-fold, seed 8008, by question) cut matching frozen lex@0.809 coverage, applied to the full-design refit",
           "K": K, "role": "primary" if K == 5 else "secondary", "sc_t": 0.7, "model": "nvidia/Nemotron-3_5-Lightning",
           "fit_slice": "docs/v8/design.json sha256 2728213ad1bba18f2228cbbdffc2a89aa60ee2db0b41adb0303ebfe91c5fc4f7", "code": "bench/v8.py, bench/v8_r2.py:feats_k"}
    s = json.dumps(cfg, sort_keys=True, indent=1); open(out, "w").write(s)
    print(hashlib.sha256(s.encode()).hexdigest()[:16], round(thr, 4), round(cov, 4), dict(zip(["bias"] + BASE, cfg["w"])))


if __name__ == "__main__":
    main(sys.argv[1])
    main(sys.argv[1], "bench/calib/v8_conf_k0.json", K=0)
