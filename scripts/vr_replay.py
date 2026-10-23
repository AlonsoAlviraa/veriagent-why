"""Offline replay of verify-retry thresholds/weights from always-retry logs (VR_THRESHOLD=101, TAT-QA TRAIN only).
Attempts in an always-retry log are a prefix-exact sequence, so the loop under any (threshold T, det weight w) is simulated
exactly (patience 2, max 5): stop at the first attempt with score>=T, return the best-scoring attempt so far.
Per-attempt EM is computed from the logged packet with the same post-step and official metric as the runner."""
import json, sys, itertools
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os; os.environ["TATQA_SPLIT"] = "train"
from bench import tatqa as TQ
D = Path(__file__).resolve().parents[1] / "data" / "bench" / "tatqa"
items = {t["id"]: t for t in TQ.items(D / "tatqa_dataset_train.json")}
rows = [json.loads(l) for l in open(sys.argv[1])]
data = []
for r in rows:
    it = items.get(r["id"])
    if not it or r.get("error"):
        continue
    att = []
    for a in r["output"]["vr_attempts"]:
        p = a.get("packet") if isinstance(a.get("packet"), dict) else None
        em = TQ.item_em(D, it, TQ._pred(p, it))[0] if p else 0.0
        att.append((a["det"], a["verifier"], em))
    data.append(att)


def sim(T, w, patience=2):
    ems, confs, n_att = [], [], []
    for att in data:
        best, stale, k = None, 0, 0
        for k, (d, v, em) in enumerate(att):
            s = w * d + (1 - w) * (v if v is not None else d)
            if best is None or s > best[0]:
                best, stale = (s, em), 0
            else:
                stale += 1
            if s >= T or stale >= patience:
                break
        ems.append(best[1]); confs.append(best[0] / 100); n_att.append(k + 1)
    n = len(ems)
    brier = sum((c - e) ** 2 for c, e in zip(confs, ems)) / n
    bins = [[] for _ in range(10)]
    for c, e in zip(confs, ems):
        bins[min(9, int(c * 10))].append((c, e))
    ece = sum(len(b) / n * abs(sum(c for c, _ in b) / len(b) - sum(e for _, e in b) / len(b)) for b in bins if b)
    return {"T": T, "w_det": w, "em": round(sum(ems) / n, 3), "attempts": round(sum(n_att) / n, 2), "ece": round(ece, 3), "brier": round(brier, 3), "n": n}


res = [sim(T, w) for T, w in itertools.product([30, 40, 50, 60, 70, 80, 90, 101], [0.3, 0.5, 0.7, 0.9])]
res.sort(key=lambda x: (-x["em"], x["attempts"], x["ece"]))
for r in res[:12]:
    print(r)
print("default T50 w0.5:", sim(50, 0.5), "single-shot:", sim(0, 0.5))
json.dump(res, open(Path(sys.argv[1]).with_suffix(".replay.json"), "w"), indent=1)
