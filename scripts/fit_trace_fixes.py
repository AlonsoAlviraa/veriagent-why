"""Fit / select trace-fix parameters on TRAIN / TUNE data only (never dev, never the 70 InsightBench eval tasks).
  span   : replay span_extend modes over existing TAT-QA TRAIN rows (no model calls) and pick the best EM.
  cr_tat : isotonic map p_correct -> EM on a TAT-QA TRAIN agent_cr run    (writes bench/calib/cr_tatqa.json)
  cr_ib  : isotonic map p_correct -> judge>=0.6 on the 30 InsightBench TUNE tasks (writes bench/calib/cr_insightbench.json)
usage: python scripts/fit_trace_fixes.py span|cr_tat <train.jsonl>|cr_ib <tune.jsonl>"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench import tatqa as TQ, fixes as FX

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "bench" / "tatqa"
CAL = ROOT / "bench" / "calib"
SPLIT = json.loads((ROOT / "bench/splits/insightbench_split.json").read_text(encoding="utf-8"))


def assert_split(rows, allowed: set):
    bad = [r["id"] for r in rows if r["id"] not in allowed]
    assert not bad, f"{len(bad)} ids outside the fitting split (e.g. {bad[:2]}): refusing"


def load(p):
    return [r for r in (json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()) if not r.get("error")]


def span(files):
    items = {it["id"]: it for it in TQ.items(D / "tatqa_dataset_train.json")}
    res = {}
    for mode in ("off", "end", "sentence", "years"):
        em = n = changed = 0
        for f in files:
            for r in load(f):
                it = items.get(r["id"])
                if not it:
                    raise SystemExit(f"{r['id']} is not a TRAIN item: refusing")
                o = r["output"]
                a, rule = FX.split_years(o.get("answer")) if mode == "years" else FX.span_extend(o.get("answer"), [p["text"] for p in it["doc"]["paragraphs"]], mode)
                changed += rule is not None
                em += TQ.item_em(D, it, {"answer": a, "scale": o.get("scale")})[0]
                n += 1
        res[mode] = {"em": round(em / n, 4), "n": n, "changed": changed}
    print(json.dumps(res))
    return res


def cr(path, bench):
    rows = load(path)
    allowed = set(SPLIT["tune"]) if bench == "insightbench" else {it["id"] for it in TQ.items(D / "tatqa_dataset_train.json")}
    assert_split(rows, allowed)
    xs, ys, ids = [], [], []
    for r in rows:
        if bench == "insightbench":
            p = (r["output"].get("v2") or {}).get("p_correct")
            y = float((r["scores"].get("summary_judge") or 0) >= 0.6)
        else:
            p = ((r["output"].get("v2") or {}).get("critic") or {}).get("p_correct")
            y = float(r["scores"]["em"] == 1)
            if not r["output"].get("gate_passed"):
                continue
        if p is not None:
            xs.append(p); ys.append(y); ids.append(r["id"])
    cmap = FX.isotonic_fit(xs, ys)
    CAL.mkdir(exist_ok=True)
    out = {"bench": bench, "source": str(path), "n": len(xs), "fit_split": "train" if bench == "tatqa" else "tune",
           "target": "EM==1 (gate-passed rows)" if bench == "tatqa" else "summary_judge>=0.6", "base_rate": round(sum(ys) / max(1, len(ys)), 4),
           "map": cmap, "ids": ids}
    (CAL / f"cr_{bench}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out))


if __name__ == "__main__":
    if sys.argv[1] == "span":
        span(sys.argv[2:] or [ROOT / "bench/results/battery/tatqa-train-post-agent_mk.jsonl", ROOT / "bench/results/battery/tatqa-train-v2-agent_cr.jsonl"])
    else:
        cr(sys.argv[2], "tatqa" if sys.argv[1] == "cr_tat" else "insightbench")
