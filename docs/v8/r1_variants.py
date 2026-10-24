"""Exploratory (post-hoc on design) offline variants from round-1 rows; no new LLM calls."""
import glob, json, os, re, sys
sys.path.insert(0, '/workspace/vw-v8'); os.environ['TATQA_SPLIT'] = 'dev'
from bench.v8_report import report, official
from bench.heldout_report import mcnemar, boot_ci
from bench.tat_post import infer_scale, postprocess
from bench.run import select
o, rows, S = report(sorted(glob.glob('/workspace/v8-eval/r1_s*.jsonl')))
items = {x['id']: x for x in select('tatqa', False, None, None) if x['id'] in rows}
def a_v7scale(r, only=None):
    v = r['output']['v8']; s0 = v['samples'][0]; e = s0['exec']
    if not e['ok'] or (only and e.get('type') not in only):
        return v['v7']
    it = items[r['id']]; raw = s0['raw']
    expr = str(raw.get('expr') or '')
    for k, a in enumerate(raw.get('args') or []):
        expr = re.sub(rf'\ba{k}\b', str(a), expr)
    pp = postprocess({'answer': e['answer'], 'expression': expr}, it['q']['question'], it['doc'])
    return {'answer': pp['answer'], 'scale': pp['scale']}
V = {'A_v7scale': lambda r: a_v7scale(r), 'A_arith_v7scale': lambda r: a_v7scale(r, {'arithmetic'}),
     'A_arith_agree2': None}
ids = sorted(rows); base = [S['v7'][i][0] for i in ids]; res = {}
for name, f in V.items():
    if f is None: continue
    em = [official(rows[i]['gold'], f(rows[i]))[0] for i in ids]
    p, fx, br = mcnemar([b >= .5 for b in base], [x >= .5 for x in em]); d, lo, hi = boot_ci(base, em)
    res[name] = {'em': round(100*sum(em)/len(ids), 2), 'fixed': fx, 'broken': br, 'delta': round(100*d, 2), 'ci95': [round(100*lo, 2), round(100*hi, 2)], 'p': round(p, 4)}
print(json.dumps(res, indent=1))
