"""Calibrate markov.RELEVANCE_MIN on the TAT-QA TRAIN split only (dev stays evaluation-only).
Oracle evidence, no LLM calls: positive = the gold source (rel_paragraphs text, or the table row holding the
answer); negative = a paragraph/row from another train document. Score both with the NVIDIA reranker (free
tier, <=35 rpm). RELEVANCE_MIN = 5th percentile of positive scores (>=95% of relevant evidence is accepted).
Usage: python scripts/calib_relevance.py [N]  -> bench/features/relevance-calib-train.json"""
import json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from bench import nv_rerank as NR
d = json.load(open(ROOT / "data/bench/tatqa/tatqa_dataset_train.json"))
rng = random.Random(20261023); N = int(sys.argv[1]) if len(sys.argv) > 1 else 150
def pos_of(doc, q):
    if q["answer_from"] == "text" and q.get("rel_paragraphs"):
        o = int(q["rel_paragraphs"][0]); return next((p["text"] for p in doc["paragraphs"] if p["order"] == o), None)
    if q["answer_from"] == "table":
        a = [str(x) for x in (q["answer"] if isinstance(q["answer"], list) else [q["answer"]])]
        for row in doc["table"]["table"]:
            if any(x and x in " ".join(row) for x in a): return " | ".join(row)
    return None
def any_ev(doc):
    c = [p["text"] for p in doc["paragraphs"]] + [" | ".join(r) for r in doc["table"]["table"][1:]]
    return rng.choice(c)
out_p = ROOT / "bench/features/relevance-calib-train.json"
res = json.loads(out_p.read_text())["items"] if out_p.exists() else []
done = {r["uid"] for r in res}
while len(res) < N:
    i = rng.randrange(len(d)); doc = d[i]; q = rng.choice(doc["questions"])
    if q["uid"] in done: continue
    pos = pos_of(doc, q)
    if not pos: continue
    neg = any_ev(d[(i + rng.randrange(1, len(d))) % len(d)])
    try: sp, sn = NR.rank(q["question"], [pos, neg])
    except Exception as e: print("err", type(e).__name__, flush=True); continue
    res.append({"uid": q["uid"], "pos": sp, "neg": sn}); done.add(q["uid"])
    if len(res) % 10 == 0:
        out_p.write_text(json.dumps({"items": res})); print(len(res), flush=True)
ps = sorted(r["pos"] for r in res); ns = [r["neg"] for r in res]
thr = ps[int(0.05 * len(ps))]
summ = {"n": len(res), "split": "train", "seed": 20261023, "RELEVANCE_MIN_p05_pos": thr,
        "pos_accept": sum(p >= thr for p in ps) / len(ps), "neg_reject": sum(n < thr for n in ns) / len(ns)}
out_p.write_text(json.dumps({"summary": summ, "items": res}, indent=1)); print(summ)
