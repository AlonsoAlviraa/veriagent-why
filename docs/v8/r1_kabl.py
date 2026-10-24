import glob, json, sys
from collections import Counter
sys.path.insert(0, '/workspace/vw-v8')
from bench.v8_report import report, oof, conf, boot_auroc_diff
from bench.v8 import key
from bench.abstention import signal as lex
o, rows, S = report(sorted(glob.glob('/workspace/v8-eval/r1_s*.jsonl')))
ids = sorted(rows); y = [int(S['v7'][i][0] >= .5) for i in ids]; sl = [lex(rows[i]['output']) for i in ids]
def feats(r, k):
    v = r['output']['v8']; sm = v['samples'][:1 + k]; e0 = sm[0]['exec']
    val = [s for s in sm if s['exec']['ok']]; votes = Counter(key(s['exec']['answer']) for s in val)
    pick = votes.most_common(1)[0][0] if votes else None
    v7k = key(v['v7']['answer'])
    return [votes[pick] / len(sm) if pick else 0, float(e0['ok']), float(bool(e0['ok'] and key(e0['answer']) == pick)),
            float(pick == v7k), float(sum(1 for s in val if key(s['exec']['answer']) == v7k) / len(sm)), lex(r['output'])]
for k in ():
    so = oof([feats(rows[i], k) for i in ids], y)
    print(k, conf(y, so), boot_auroc_diff(y, sl, so))
sl_cal = oof([[s] for s in sl], y)
print('lex_calibrated_oof', conf(y, sl_cal))
so = oof([feats(rows[i], 3) for i in ids], y)
import random
rng = random.Random(2026); n=len(y); d=[]
from bench.heldout_report import ece
for _ in range(2000):
    ix=[rng.randrange(n) for _ in range(n)]
    d.append(ece([y[i] for i in ix],[sl_cal[i] for i in ix])-ece([y[i] for i in ix],[so[i] for i in ix]))
d.sort(); print('ECE(lexcal)-ECE(k3) ci95', round(d[50],4), round(d[1949],4))
