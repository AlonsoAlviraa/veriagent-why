"""Eval harness: VeriAgent Why vs plain-RAG baseline on the same questions/data/budget.

python eval/eval.py --split dev            (any number of times; for tuning)
python eval/eval.py --split test --freeze  (verifies the frozen hash; writes eval/RESULTS_<provider>.md)
Metric: exact match of top_cause_label vs eval/ground truth in questions.json. Reported as k/n
with a Wilson 95% interval. No significance claims. Ground truth is read only here.
"""
from __future__ import annotations
import argparse, hashlib, json, math, sys, time
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "eval"))
from app.pipeline import run  # noqa: E402
from app.config import provider  # noqa: E402
from baseline_rag import run_baseline  # noqa: E402


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    qs = json.loads((R / "eval" / "questions.json").read_text())
    if a.split == "test":
        h = hashlib.sha256(json.dumps([q for q in qs if q["split"] == "test"], sort_keys=True).encode()).hexdigest()
        if h != (R / "eval" / "SPLITS.sha256").read_text().split()[0]:
            sys.exit("test split hash mismatch: the frozen test set was modified")
        if not a.freeze:
            sys.exit("use --freeze to run the test split")
    rows = []
    for q in [q for q in qs if q["split"] == a.split]:
        t0 = time.time()
        res = run(q["input"], f"eval-{q['qid']}")
        r = res["output"]["result"]
        b = run_baseline(q["input"], r["token_report"]["s1_filter"]["actual_total"])
        rows.append({"qid": q["qid"], "kind": q["kind"], "expected": q["expected_label"],
                     "agent": r["analysis"]["top_cause_label"], "agent_status": res["status"], "agent_confidence": r["confidence"]["confidence"],
                     "baseline": b["label"], "baseline_context_tokens": b["context_tokens"],
                     "agent_s2_context_tokens": r["token_report"]["s1_filter"]["actual_total"], "log": res["log_file"], "secs": round(time.time() - t0, 2)})
        print(json.dumps(rows[-1]))
    n = len(rows)
    ka = sum(x["agent"] == x["expected"] for x in rows); kb = sum(x["baseline"] == x["expected"] for x in rows)
    out = {"split": a.split, "provider": provider(), "n": n, "agent_k": ka, "agent_wilson95": wilson(ka, n),
           "baseline_k": kb, "baseline_wilson95": wilson(kb, n), "rows": rows}
    (R / "eval" / f"results_{a.split}_{provider()}.json").write_text(json.dumps(out, indent=2) + "\n")
    f = lambda k, ci: f"{k}/{n} (Wilson 95% CI {ci[0]:.2f}–{ci[1]:.2f})"
    md = [f"# Eval results: {a.split} split, provider `{provider()}`", "",
          "Measured by `eval/eval.py` on seeded synthetic data. Metric: exact match of `top_cause_label`.", "",
          f"| System | Correct |", "|---|---|", f"| VeriAgent Why | {f(ka, out['agent_wilson95'])} |", f"| Plain-RAG baseline | {f(kb, out['baseline_wilson95'])} |", "",
          "| qid | kind | expected | agent | baseline |", "|---|---|---|---|---|"]
    md += [f"| {x['qid']} | {x['kind']} | {x['expected']} | {x['agent']} | {x['baseline']} |" for x in rows]
    (R / "eval" / f"RESULTS_{a.split}_{provider()}.md").write_text("\n".join(md) + "\n")
    print(f"agent {ka}/{n} {out['agent_wilson95']}  baseline {kb}/{n} {out['baseline_wilson95']}")


if __name__ == "__main__":
    main()
