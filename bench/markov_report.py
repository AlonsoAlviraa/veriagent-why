"""Before/after table for the Markovian control sample (agent vs agent_mk vs agent_mknv vs agent_mkr).

    python -m bench.markov_report bench/results/tatqa-markov-sample.jsonl bench/results/tatqa-markov-rerank-sample.jsonl
"""
from __future__ import annotations
import json, statistics as S, sys
from collections import Counter

ORDER = ["agent", "agent_mk", "agent_mknv", "agent_mkr"]


def load(paths):
    recs = {}
    for p in paths:
        for line in open(p):
            r = json.loads(line)
            if not r.get("error"):
                recs[(r["system"], r["id"])] = r  # last successful record wins (resume)
    return list(recs.values())


def m(xs):
    xs = [x for x in xs if x is not None]
    return round(S.mean(xs), 3) if xs else None


def ratio(a, b):
    return round(a / b, 3) if b else None


def table(recs):
    bench = recs[0]["bench"]
    ids = {}
    for r in recs:
        ids.setdefault(r["system"], set()).add(r["id"])
    common = set.intersection(*ids.values())
    rows = []
    for s in [x for x in ORDER if x in ids]:
        R = [r for r in recs if r["system"] == s and r["id"] in common]
        row = {"system": s, "n": len(R), "llm_calls/item": m([r["meter"]["calls"] for r in R]),
               "wall_s/item": m([r["seconds"] for r in R]),
               "tokens/item": m([r["meter"]["prompt_tokens"] + r["meter"]["completion_tokens"] for r in R]),
               "usd": round(sum(r["meter"].get("nebius_usd") or 0 for r in R), 4)}
        ex = [r["explain"] for r in R]
        row["claims_traceable"] = ratio(sum(e.get("claims_traceable") or 0 for e in ex), sum(e.get("claims") or 0 for e in ex))
        row["citations_valid"] = ratio(sum(e.get("citations_valid") or 0 for e in ex), sum(e.get("citations") or 0 for e in ex))
        if bench == "tatqa":
            row |= {"EM": m([r["scores"]["em"] for r in R]), "F1": m([r["scores"]["f1"] for r in R]),
                    "EM_k": sum(r["scores"]["em"] for r in R),
                    "unsupported_num_rate": round(1 - m([float(r["scores"]["traceable"]) for r in R]), 3),
                    "gate_pass": m([float(bool(r["output"].get("gate_passed"))) for r in R])}
        else:
            row |= {"insight_ROUGE1": m([r["scores"]["insight_rouge1"] for r in R]), "summary_ROUGE1": m([r["scores"]["summary_rouge1"] for r in R]),
                    "summary_judge": m([r["scores"].get("summary_judge") for r in R]),
                    "faithfulness": m([(r["explain"].get("faithfulness") or {}).get("score") if isinstance(r["explain"].get("faithfulness"), dict) else r["explain"].get("faithfulness") for r in R]),
                    "numbers_unsupported": ratio(sum(e.get("numbers_unsupported") or 0 for e in ex), sum(e.get("numbers") or 0 for e in ex)),
                    "sql_error_rate": ratio(sum(r["output"].get("sql_errors") or 0 for r in R), sum(r["output"].get("queries") or 0 for r in R))}
        dec = Counter((d["decision"], d["action"]) for r in R for d in (r["output"].get("decisions") or []))
        row["decisions"] = {f"{k}={a}": n for (k, a), n in sorted(dec.items())}
        rs = [x for r in R for x in (r["output"].get("rerank_seconds") or [])]
        if rs:
            row["rerank_calls"], row["rerank_s/call"] = len(rs), m(rs)
        rows.append(row)
    return bench, len(common), rows


if __name__ == "__main__":
    b, n, rows = table(load(sys.argv[1:]))
    print(json.dumps({"bench": b, "common_items": n, "rows": rows}, indent=1))
