"""Fit verify-v2 critic (agent_cr) threshold + confidence map on TAT-QA TRAIN only (never dev).
Input: bench/results/battery/tatqa-train-v2-agent_cr.jsonl (each row logs critic p_correct and the always-computed revision).
Replay: for each T, final = revision if p_correct < T and revision passed the gate, else agent_mk answer; EM via the official scorer.
Confidence map: bins on p_correct of kept answers -> empirical accuracy (Laplace-smoothed). Prints env exports for the dev run."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench import tatqa as TQ

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "bench" / "tatqa"
rows = {}
for l in (ROOT / "bench/results/battery/tatqa-train-v2-agent_cr.jsonl").read_text().splitlines():
    r = json.loads(l)
    if not r.get("error"):
        rows[r["id"]] = r
items = {it["id"]: it for it in TQ.items(D / "tatqa_dataset_train.json") if it["id"] in rows}
recs = []
for i, r in rows.items():
    v2 = r["output"]["v2"]
    rev = v2.get("revision")
    rev_em = TQ.item_em(D, items[i], rev)[0] if rev else None
    recs.append((v2["critic"]["p_correct"], r["scores"]["em"], rev_em, bool(rev and rev["gate_passed"]), r["output"].get("gate_passed")))
n = len(recs)
grid = []
for T in [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.01]:
    em = sum((re_ if (p is not None and p < T and ok and re_ is not None) else e) for p, e, re_, ok, _ in recs) / n
    grid.append((round(em, 4), -T, T))
best = max(grid)  # ties -> smaller T (fewer revisions)
print(json.dumps({"n_train": n, "grid": [(T, em) for em, _, T in grid], "chosen_T": best[2]}))
edges = [0.5, 0.8, 0.95, 1.0]
cmap, lo = [], -1
for hi in edges:
    b = [e for p, e, _, _, g in recs if p is not None and lo < p <= hi and g]
    cmap.append([hi, round((sum(b) + 1) / (len(b) + 2), 3)])
    lo = hi
print(json.dumps({"conf_map": cmap}))
print(f"export CR_THRESHOLD={best[2]} CR_CONF_MAP='{json.dumps(cmap)}'")
