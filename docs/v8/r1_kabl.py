"""K ablation with the PRODUCTION features (bench.v8_r2.feats_k == bench.v8 features on pointer-0 + first k T=0.7 samples,
+ lex), OOF 5-fold (same folds as the candidate). Exploratory: k is NOT re-chosen from this (primary stays k=5)."""
import glob, sys
sys.path.insert(0, '/workspace/vw-v8')
from bench.v8_r2 import feats_k, oof
from bench.v8_report import report, conf
_, rows, S = report(sorted(glob.glob(sys.argv[1] if len(sys.argv) > 1 else '/workspace/v8-eval/r1_s*.jsonl')))
ids = sorted(rows); y = [int(S['v7'][i][0] >= .5) for i in ids]
for k in range(6):
    print(k, conf(y, oof([feats_k(rows[i]['output'], k) for i in ids], y)))
