"""Summarise a results JSONL per system: n, k/n + Wilson 95% CI, means, cost per item.

    python -m bench.report bench/results/insightbench-live.jsonl [--md out.md]
InsightBench k/n: items whose summary judge >= 0.6 (our threshold, declared) and items whose
insight ROUGE-1 >= 0.25 (our threshold). Means are the official-style continuous scores.
TAT-QA k/n: exact match (official scorer, per item); unsupported-number rate over numeric answers.
"""
from __future__ import annotations
import argparse, json, statistics as st
from collections import defaultdict
from .common import bootstrap_mean, brier, ece, wilson


def load(path):
    rows = {}
    for line in open(path):
        r = json.loads(line)
        rows[(r["system"], r["id"])] = r  # last record wins (resume)
    return list(rows.values())


def kn(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({lo:.2f}-{hi:.2f})"


def mci(xs):
    if not xs:
        return None
    lo, hi = bootstrap_mean(xs)
    return f"{st.mean(xs):.3f} ({lo:.3f}-{hi:.3f})"


def rate(k, n):
    return kn(k, n) if n else "n/a"


def calib(rows, conf_key, correct_fn):
    pairs = [(r["output"].get(conf_key), correct_fn(r)) for r in rows]
    pairs = [(c, int(y)) for c, y in pairs if c is not None]
    if not pairs:
        return None
    c, y = [p[0] for p in pairs], [p[1] for p in pairs]
    return f"ECE {ece(c, y):.3f} / Brier {brier(c, y):.3f} (n={len(pairs)}, mean conf {st.mean(c):.2f}, acc {st.mean(y):.2f})"


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
            d.update(calls_per_item=round(st.mean(calls), 1), tokens_per_item=round(st.mean(toks)),
                     nebius_usd_total=round(sum(r["meter"].get("nebius_usd", 0) + ((r.get("judge_meter") or {}).get("nebius_usd") or 0) for r in ok), 4),
                     sec_per_item=round(st.mean(r["seconds"] for r in ok), 1))
        sc = [r["scores"] for r in ok]
        ex = [r.get("explain") or {} for r in ok]
        if rs and rs[0]["bench"] == "insightbench":
            scored = [r for r in ok if not r["scores"].get("excluded")]
            d["n_scored"] = len(scored)
            d["excluded"] = sorted(r["id"] for r in ok if r["scores"].get("excluded"))
            # errors count as 0 in means (conservative)
            pad = [0.0] * d["errors"]
            for k in ("insight_rouge1", "summary_rouge1", "summary_judge", "insight_judge"):
                v = [r["scores"][k] for r in scored if r["scores"].get(k) is not None]
                if v:
                    d[k] = mci(v + pad)
            # fix (audit #6): a None verdict (judge reply unparseable) is excluded and counted, not scored as 0
            jv = [r for r in scored if r["scores"].get("summary_judge") is not None]
            d["judge_none"] = len(scored) - len(jv)
            d["judge>=0.6 (secondary)"] = rate(sum(r["scores"]["summary_judge"] >= 0.6 for r in jv), len(jv) + d["errors"])
            d["rouge>=0.25 (secondary)"] = rate(sum(r["scores"]["insight_rouge1"] >= 0.25 for r in scored), len(scored) + d["errors"])
            q = sum(r["output"].get("queries") or 0 for r in ok)
            if q:
                d["sql_error_rate_final"] = rate(sum(r["output"].get("sql_errors") or 0 for r in ok), q)
                d["sql_error_rate_first_try"] = rate(sum(r["output"].get("sql_errors_first_try", r["output"].get("sql_errors")) or 0 for r in ok), q)
            d["dropped_by_gate"] = sum(r["output"].get("dropped_by_gate", 0) for r in ok)
            if any(ex):
                d["citation_precision"] = rate(sum(e.get("citations_valid", 0) for e in ex), sum(e.get("citations", 0) for e in ex))
                d["claim_traceability"] = rate(sum(e.get("claims_traceable", 0) for e in ex), sum(e.get("claims", 0) for e in ex))
                d["unsupported_number_rate"] = rate(sum(e.get("numbers_unsupported", 0) for e in ex), sum(e.get("numbers", 0) for e in ex))
                d["faithfulness_judge"] = mci([e["faithfulness"] for e in ex if e.get("faithfulness") is not None])
            good = lambda r: (r["scores"].get("summary_judge") or 0) >= 0.6  # None -> not good (paired comparison; judge_none reported)
            d["calibration_self"] = calib(scored, "confidence", good)
            d["calibration_det"] = calib(scored, "confidence_det", good)
        else:
            d["EM"] = kn(sum(x.get("em", 0) == 1 for x in sc), len(rs))
            d["F1_mean"] = mci([x.get("f1", 0) for x in sc] + [0.0] * d["errors"])
            if any("em_raw" in x for x in sc):
                d["EM_raw_no_post"] = kn(sum(x.get("em_raw", 0) == 1 for x in sc), len(rs))
                d["F1_raw_no_post"] = mci([x.get("f1_raw", 0) for x in sc] + [0.0] * d["errors"])
            types = defaultdict(list)
            for r in ok:
                types[r["gold"]["answer_type"]].append(r["scores"])
            d["by_answer_type"] = {t: f"EM {st.mean(x.get('em', 0) for x in v):.3f} F1 {st.mean(x.get('f1', 0) for x in v):.3f} (n={len(v)})" for t, v in sorted(types.items())}
            num = [x for x in sc if x.get("numeric_answer")]
            d["unsupported_numbers"] = kn(sum(not x["traceable"] for x in num), len(num))
            if any(ex):
                d["citation_precision"] = rate(sum(e.get("citations_valid", 0) for e in ex), sum(e.get("citations", 0) for e in ex))
                d["claim_traceability"] = rate(sum(e.get("claims_traceable", 0) for e in ex), sum(e.get("claims", 0) for e in ex))
            d["calibration_self"] = calib(ok, "confidence", lambda r: r["scores"].get("em", 0) == 1)
            d["calibration_det"] = calib(ok, "confidence_det", lambda r: r["scores"].get("em", 0) == 1)
        out.append({k: v for k, v in d.items() if v is not None})
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
        lines += ["| " + " | ".join(str(d.get(k, "")).replace("|", "/") for k in keys) + " |" for d in res]
        open(a.md, "w").write("\n".join(lines) + "\n")
