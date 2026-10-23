"""Re-judge stored InsightBench records with JUDGE_MODEL (default Super), without re-running the systems.
Same judge() / faithfulness() code as bench.run; the old verdicts are kept under *_prev. Resumable.
usage: python -m bench.rejudge IN.jsonl OUT.jsonl"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from . import explain as EX, insightbench as IB
from .llmio import JUDGE_MODEL, Meter

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    src, dst = map(Path, (argv or sys.argv[1:])[:2])
    os.environ.setdefault("LLM_PROVIDER", "nebius")
    os.environ["MODEL_MIN_INTERVAL_S"] = os.environ.get("MODEL_MIN_INTERVAL_S", "0.5")
    done = {json.loads(l)["id"] + "|" + json.loads(l)["system"] for l in dst.open()} if dst.exists() else set()
    root = ROOT / "data" / "bench" / "insightbench"
    with dst.open("a") as fo:
        for line in src.open():
            r = json.loads(line)
            if r.get("error") or r["id"] + "|" + r["system"] in done:
                continue
            t = IB.load_task(root / "data" / "notebooks" / f"{r['id']}.json", root)
            jm = Meter(4, False)
            out = r["output"]
            gt = [x for x in (t.get("insights") or []) if str(x).strip()]
            sc = r["scores"]
            sc["summary_judge_prev"] = sc.get("summary_judge")
            sc.pop("excluded", None)
            if not gt:
                sc["excluded"] = "empty ground-truth insights in the dataset"
            pred_sum = out.get("summary") or " ".join(out.get("insights") or [])
            sc["summary_judge"] = IB.judge(jm, pred_sum, t.get("summary") or "") if pred_sum else 0.0
            ex = r.get("explain") or {}
            ex["faithfulness_prev"] = ex.get("faithfulness")
            ex["faithfulness"] = EX.faithfulness(jm, out)
            r["explain"], r["judge_meter"], r["judge_model"] = ex, jm.snapshot(), JUDGE_MODEL
            fo.write(json.dumps(r) + "\n"); fo.flush()
            print(r["system"], r["id"], sc["summary_judge"], ex["faithfulness"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
