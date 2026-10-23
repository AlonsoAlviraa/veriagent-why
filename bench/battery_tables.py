"""Markdown tables for docs/BENCHMARKS.md 'Markov control battery n=100' (reads bench/results/battery/*.jsonl).
TAT-QA: all 100 dev items. InsightBench: the 70 EVAL tasks of bench/splits/insightbench_split.json only
(pre-fix files: the Super re-judged *.rj.jsonl). 95% CIs: Wilson for k/n, bootstrap for means."""
from __future__ import annotations
import json, os, statistics as st, sys
from pathlib import Path
from .report import load, summarise
from .run import select

CONFIGS = ("agent", "agent_mk", "agent_mknv", "agent_mkr", "agent_vr", "react", "rag")
B = Path(__file__).resolve().parent / "results" / "battery"
SPLIT = json.loads((Path(__file__).resolve().parent / "splits" / "insightbench_split.json").read_text())


def rows(name, ids=None):
    p = B / f"{name}.jsonl"
    if not p.exists():
        return None
    r = load(p)
    return [x for x in r if ids is None or x["id"] in ids]


def extra(rs):
    att = [x["output"].get("vr_n_attempts") for x in rs if x["output"].get("vr_n_attempts")]
    sup = sum(sum(v for k, v in (x.get("models_used") or (x.get("meter") or {}).get("providers") or {}).items() if "super" in k.lower()) for x in rs)
    allc = sum(sum((x.get("models_used") or (x.get("meter") or {}).get("providers") or {}).values()) for x in rs)
    return {"attempts/item": f"{st.mean(att):.2f}" if att else "", "Super share of calls": f"{sup}/{allc}" if allc else ""}


def table(cols, lines):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    return "\n".join(out + ["| " + " | ".join(str(c).replace("|", "/") for c in l) + " |" for l in lines])


def tat(tags, ids=None, title=""):
    cols = ["config", "EM", "F1", "citation precision", "calibration (det conf)", "attempts/item", "$ total", "s/item"]
    L = []
    for tag in tags:
        for s in CONFIGS:
            r = rows(f"tatqa-{tag}-{s}", ids)
            if not r:
                continue
            d = summarise(r)[0]
            L.append([f"{s} ({tag})", d["EM"], d.get("F1_mean"), d.get("citation_precision", ""), d.get("calibration_det", ""),
                      extra(r)["attempts/item"], d.get("nebius_usd_total"), d.get("sec_per_item")])
    return f"**{title}**\n\n" + table(cols, L)


def ib(tags, title=""):
    ids = set(SPLIT["eval"])
    cols = ["config", "n scored", "summary judge mean", "judge>=0.6", "judge None", "insight ROUGE-1", "faithfulness", "unsupported numbers", "calibration (det)", "attempts/item", "$ total (system+judge)", "s/item"]
    L = []
    for tag in tags:
        for s in CONFIGS:
            r = rows(f"insightbench-{tag}-{s}.rj", ids) or rows(f"insightbench-{tag}-{s}", ids)
            if not r:
                continue
            d = summarise(r)[0]
            L.append([f"{s} ({tag})", d.get("n_scored"), d.get("summary_judge"), d.get("judge>=0.6 (secondary)"), d.get("judge_none"),
                      d.get("insight_rouge1"), d.get("faithfulness_judge", ""), d.get("unsupported_number_rate", ""), d.get("calibration_det", ""),
                      extra(r)["attempts/item"], d.get("nebius_usd_total"), d.get("sec_per_item")])
    return f"**{title}**\n\n" + table(cols, L)


def causes(run_prefix: str) -> str:
    """Counts by failure cause from bench/results/traces/<run>/audit_index.jsonl (last record per (config, id))."""
    root = Path(__file__).resolve().parent / "results" / "traces"
    cnt, cols = {}, set()
    for idx in sorted(root.glob(f"{run_prefix}-*/audit_index.jsonl")):
        last = {}
        for l in idx.read_text().splitlines():
            r = json.loads(l)
            last[(r["config"], r["id"])] = r
        for r in last.values():
            if r["bench"] == "insightbench" and r["id"] not in SPLIT["eval"]:
                continue
            cnt.setdefault(r["config"], {}).setdefault(r["failure_cause"], 0)
            cnt[r["config"]][r["failure_cause"]] += 1
            cols.add(r["failure_cause"])
    cols = sorted(cols)
    return table(["config"] + cols, [[c] + [cnt[c].get(k, 0) for k in cols] for c in CONFIGS if c in cnt])


if __name__ == "__main__":
    pre_ids = {x["id"] for x in (rows("tatqa-pre-agent") or [])}
    print(tat(["post"], None, "TAT-QA dev, n=150, Lightning only (main table, post-fix)"))
    print()
    print(tat(["pre", "post"], pre_ids, "TAT-QA dev before/after, the same 100 items (pre-fix vs post-fix)"))
    print()
    print(ib(["pre", "post"], "InsightBench, 70 eval tasks, Lightning only, judge = Nemotron Super"))
    print()
    print("**Failure causes, TAT-QA dev post (audit_index)**\n\n" + causes("tatqa-post"))
    print()
    print("**Failure causes, InsightBench eval post (audit_index)**\n\n" + causes("insightbench-post"))
