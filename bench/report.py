"""Summarise a results JSONL per system: n, k/n + Wilson 95% CI, means, cost per item.

    python -m bench.report bench/results/insightbench-live.jsonl [--md out.md]
InsightBench k/n: items whose summary judge >= 0.6 (our threshold, declared) and items whose
insight ROUGE-1 >= 0.25 (our threshold). Means are the official-style continuous scores.
TAT-QA k/n: exact match (official scorer, per item); unsupported-number rate over numeric answers.
"""
from __future__ import annotations
import argparse, json, statistics as st
from collections import defaultdict
from .common import wilson


def load(path):
    rows = {}
    for line in open(path):
        r = json.loads(line)
        rows[(r["system"], r["id"])] = r  # last record wins (resume)
    return list(rows.values())


def kn(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({lo:.2f}-{hi:.2f})"


def summarise(rows) -> list[dict]:
    by = defaultdict(list)
    for r in rows:
        by[r["system"]].append(r)
    out = []
    for s, rs in sorted(by.items()):
        ok = [r for r in rs if not r.get("error")]
        d = {"system": s, "n": len(rs), "errors": len(rs) - len(ok)}
        calls = [r["meter"]["calls"] + ((r.get("judge_meter") or {}).get("calls") or 0) for r in ok]
        toks = [r["meter"]["prompt_tokens"] + r["meter"]["completion_tokens"] for r in ok]
        if ok:
            d.update(calls_per_item=round(st.mean(calls), 1), sys_calls_per_item=round(st.mean(r["meter"]["calls"] for r in ok), 1),
                     tokens_per_item=round(st.mean(toks)),
                     nebius_usd_total=round(sum(r["meter"].get("nebius_usd", 0) + ((r.get("judge_meter") or {}).get("nebius_usd") or 0) for r in ok), 4),
                     models=sorted({r.get("model") or "" for r in ok}), sec_per_item=round(st.mean(r["seconds"] for r in ok), 1))
        sc = [r["scores"] for r in ok]
        if rs and rs[0]["bench"] == "insightbench":
            for k in ("insight_rouge1", "summary_rouge1", "summary_judge", "insight_judge"):
                v = [x[k] for x in sc if x.get(k) is not None]
                if v:
                    d[k] = round(st.mean(v), 3)
            j = [x.get("summary_judge") for x in sc if x.get("summary_judge") is not None]
            d["judge>=0.6"] = kn(sum(v >= 0.6 for v in j), len(rs)) if j else None
            d["rouge>=0.25"] = kn(sum(x["insight_rouge1"] >= 0.25 for x in sc), len(rs))
            d["dropped_by_gate"] = sum(r["output"].get("dropped_by_gate", 0) for r in ok)
        else:
            d["EM"] = kn(sum(x.get("em", 0) == 1 for x in sc), len(rs))
            d["F1_mean"] = round(st.mean([x.get("f1", 0) for x in sc] + [0] * d["errors"]), 3) if rs else None
            num = [x for x in sc if x.get("numeric_answer")]
            d["unsupported_numbers"] = kn(sum(not x["traceable"] for x in num), len(num))
        out.append(d)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--md")
    a = ap.parse_args()
    res = summarise(load(a.path))
    for d in res:
        print(json.dumps(d))
    if a.md:
        keys = list(dict.fromkeys(k for d in res for k in d))
        lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
        lines += ["| " + " | ".join(str(d.get(k, "")) for k in keys) + " |" for d in res]
        open(a.md, "w").write("\n".join(lines) + "\n")
