"""Before/after table for the trace-fix round: EM/F1/ECE (TAT-QA), judge mean / judge>=0.6 / ECE (InsightBench),
calls per item, spend, and paired significance (bootstrap + McNemar) vs a reference run on the SAME item ids.
Usage: .venv/bin/python scripts/compare_fix.py REF.jsonl:SYS NEW.jsonl:SYS [...]   (first arg = reference)"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench.stats import paired_bootstrap, mcnemar  # noqa: E402


def load(spec):
    p, sys_ = spec.rsplit(":", 1)
    rows = {}
    for l in Path(p).read_text().splitlines():
        r = json.loads(l)
        if r.get("system") == sys_ and not r.get("error"):
            rows[r["id"]] = r
    return rows


def ece(conf, y, bins=10):
    tot, e = len(y), 0.0
    for b in range(bins):
        idx = [i for i, c in enumerate(conf) if (b / bins <= c < (b + 1) / bins) or (b == bins - 1 and c == 1)]
        if idx:
            e += len(idx) / tot * abs(sum(conf[i] for i in idx) / len(idx) - sum(y[i] for i in idx) / len(idx))
    return round(e, 4)


def metrics(rows, ids):
    r0 = rows[ids[0]]
    tat = r0["bench"] == "tatqa"
    conf = [float((rows[i]["output"].get("confidence_det") if rows[i]["output"].get("confidence_det") is not None else rows[i]["output"].get("confidence")) or 0) for i in ids]
    calls = [rows[i]["meter"].get("calls", 0) for i in ids]
    usd = sum(rows[i]["meter"].get("nebius_usd", 0) + (rows[i].get("judge_meter") or {}).get("nebius_usd", 0) for i in ids)
    if tat:
        em = [float(rows[i]["scores"]["em"]) for i in ids]
        f1 = [float(rows[i]["scores"]["f1"]) for i in ids]
        return {"n": len(ids), "EM": round(sum(em) / len(em), 4), "F1": round(sum(f1) / len(f1), 4), "ECE": ece(conf, em),
                "calls/item": round(sum(calls) / len(ids), 2), "usd": round(usd, 4)}, em, [e == 1 for e in em]
    j = [float(rows[i]["scores"].get("summary_judge") or 0) for i in ids]
    y = [x >= 0.6 for x in j]
    return {"n": len(ids), "judge_mean": round(sum(j) / len(j), 4), "judge>=0.6": round(sum(y) / len(y), 4), "ECE": ece(conf, [float(v) for v in y]),
            "calls/item": round(sum(calls) / len(ids), 2), "usd": round(usd, 4)}, j, y


def main(specs):
    ref = load(specs[0])
    out = []
    for s in specs:
        rows = load(s)
        ids = sorted(set(rows) & set(ref))
        m, cont, binv = metrics(rows, ids)
        _, rc, rb = metrics(ref, ids)
        m["vs_ref"] = None if s == specs[0] else {"bootstrap": paired_bootstrap(rc, cont), "mcnemar": mcnemar(rb, binv)}
        out.append({"run": s, **m})
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(sys.argv[1:])
