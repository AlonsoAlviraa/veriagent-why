"""Generate the example audit traces (selection documented in docs/AUDIT_TRACE.md)."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from .audit_trace import build, find_row, load_failures

CASES = [  # (label, results file, config, id)
    ("tatqa_correct_evidence_scale_inferred", "tatqa-markov-sample.jsonl", "agent_mk", "4f17ed1a-05b0-4a69-bcb7-40f42edd6d62"),
    ("tatqa_correct_multispan", "tatqa-markov-sample.jsonl", "agent_mk", "41ae87c6-453a-4674-a4de-d886714df9d0"),
    ("tatqa_scale_failure", "tatqa-markov-sample.jsonl", "agent_mk", "8757782d-306d-4a0d-b22e-ab0f2b58171c"),
    ("tatqa_format_rounding_failure", "tatqa-markov-sample.jsonl", "agent", "e6655bf9-a024-476a-b3dc-4aaf6ae67ba0"),
    ("tatqa_citation_failure", "tatqa-markov-sample.jsonl", "agent_mk", "a8b031ed-58ec-418a-a229-89ad5444a6bb"),
    ("tatqa_arithmetic_failure", "tatqa-markov-sample.jsonl", "agent_mk", "1148519a-e611-4859-8ebd-d87eed5ed048"),
    ("insightbench_good", "insightbench-markov-sample.jsonl", "agent", "flag-8"),
    ("insightbench_paraphrase", "insightbench-markov-sample.jsonl", "agent_mk", "flag-1"),
    ("insightbench_sql_error", "insightbench-markov-sample.jsonl", "agent_mk", "flag-18"),
    ("insightbench_wrong_insight", "insightbench-markov-sample.jsonl", "agent_mknv", "flag-7"),
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default="bench/results")
    ap.add_argument("--data", default="data/bench")
    ap.add_argument("--failures")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out, fails, allt = Path(a.out), load_failures(a.failures), []
    out.mkdir(parents=True, exist_ok=True)
    for label, f, cfg, iid in CASES:
        p = Path(a.results_dir) / f
        t = {"label": label, **build(find_row(p, cfg, iid), p, Path(a.data), fails)}
        (out / f"{label}.json").write_text(json.dumps(t, indent=2, ensure_ascii=False, default=str))
        allt.append(t)
        print(label, t["secret_scan"]["redactions"], t["narrative"][:120])
    (out / "audit_all.json").write_text(json.dumps({"schema_version": "audit-trace/1", "cases": allt}, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
