"""Benchmark runner: resumable JSONL, hard call budget, pacing, --limit, --dry-run, --offline.

    python -m bench.run --bench insightbench --systems agent,rag,react --limit 3 --max-calls 300 --rpm 30
    python -m bench.run --bench tatqa --systems agent,rag,react --limit 15 --max-calls 300 --rpm 30
    python -m bench.run --bench insightbench --offline --fixtures      # CI smoke, no network
    python -m bench.report bench/results/<file>.jsonl

Live mode uses LLM_PROVIDER (default nvidia here) with NVIDIA_API_KEY from env/.env (never printed).
--rpm sets the client-side pacer (MODEL_MIN_INTERVAL_S = 60/rpm) shared by every model call.
"""
from __future__ import annotations
import argparse, json, os, random, time, traceback
from pathlib import Path
from . import explain as EX, insightbench as IB, tatqa as TQ
from .llmio import JUDGE_MODEL, BudgetExceeded, Meter, NebiusHardStop

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "bench"
FIX = Path(__file__).resolve().parent / "fixtures"
SEED = 2026


def select(bench: str, fixtures: bool, limit: int | None, ids: list[str] | None):
    if bench == "insightbench":
        root = FIX / "insightbench" if fixtures else DATA / "insightbench"
        files = sorted((root / "data" / "notebooks").glob("flag-*.json"), key=lambda p: int(p.stem.split("-")[1]))
        tasks = [IB.load_task(f, root) for f in files]
        for t in tasks:
            t["_root"] = root
    else:
        root = FIX / "tatqa" if fixtures else DATA / "tatqa"
        tasks = TQ.items(root / ("tatqa_fixture.json" if fixtures else f"tatqa_dataset_{os.environ.get('TATQA_SPLIT', 'dev')}.json"))  # TATQA_SPLIT=train: calibration only
        random.Random(SEED).shuffle(tasks)  # fixed, documented sample order (seed 2026) over the dev split
    if ids:
        tasks = [t for t in tasks if t["id"] in ids]
    return tasks[:limit] if limit else tasks


def done_keys(path: Path) -> set:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not r.get("error"):
            out.add((r["system"], r["id"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=["insightbench", "tatqa"], required=True)
    ap.add_argument("--systems", default="agent,rag,react")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="comma-separated task ids")
    ap.add_argument("--max-calls", type=int, default=200, help="hard cap on model calls for this whole run (incl. judge)")
    ap.add_argument("--max-calls-item", type=int, default=40, help="hard cap per item")
    ap.add_argument("--rpm", type=float, default=30.0)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--no-trace", action="store_true", help="do not write per-item audit traces (bench/results/traces/)")
    ap.add_argument("--trace-dir", default=str(Path(__file__).resolve().parent / "results" / "traces"))
    ap.add_argument("--judge-insights", action="store_true", help="InsightBench o2m insight judge (|gt|x|pred| calls)")
    ap.add_argument("--faith-sample", type=int, default=30, help="InsightBench: LLM-judge faithfulness on the first N tasks per system (0=off)")
    ap.add_argument("--offline", action="store_true", help="scripted fake model, no network (CI)")
    ap.add_argument("--fixtures", action="store_true", help="use bench/fixtures instead of data/bench")
    ap.add_argument("--dry-run", action="store_true", help="list what would run, no model calls")
    ap.add_argument("--out", help="results JSONL (default bench/results/<bench>-<mode>.jsonl)")
    a = ap.parse_args(argv)

    systems = [s for s in a.systems.split(",") if s]
    tasks = select(a.bench, a.fixtures, a.limit, a.ids.split(",") if a.ids else None)
    out = Path(a.out) if a.out else ROOT / "bench" / "results" / f"{a.bench}-{'offline' if a.offline else 'live'}.jsonl"
    done = done_keys(out)
    todo = [(s, t) for t in tasks for s in systems if (s, t["id"]) not in done]
    print(f"{a.bench}: {len(tasks)} items x {len(systems)} systems; {len(todo)} to run, {len(done)} already done -> {out}")
    if a.dry_run:
        for s, t in todo:
            print(f"  would run {s} on {t['id']}")
        return 0
    if not a.offline:
        from app.config import load_dotenv
        load_dotenv()
        os.environ["SAMPLE_MODE"] = "false"
        os.environ.setdefault("LLM_PROVIDER", "nvidia")
        if os.environ["LLM_PROVIDER"] == "nvidia" and not os.environ.get("NVIDIA_API_KEY"):
            raise SystemExit("NVIDIA_API_KEY not set (env or .env)")
        os.environ["MODEL_MIN_INTERVAL_S"] = str(60.0 / a.rpm)
        os.environ.setdefault("MODEL_TIMEOUT_S", "90")
    out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    order = {t["id"]: i for i, t in enumerate(tasks)}
    for s, t in todo:
        if total >= a.max_calls:
            print(f"run budget reached ({a.max_calls} calls); stopping, rerun to resume")
            break
        m = Meter(min(a.max_calls_item, a.max_calls - total), a.offline)
        rec = {"bench": a.bench, "system": s, "id": t["id"], "mode": "offline" if a.offline else "live",
               "provider": None if a.offline else os.environ.get("LLM_PROVIDER"),
               "model": None if a.offline else (os.environ.get("NEBIUS_MODEL", "nvidia/Nemotron-3_5-Lightning") if os.environ.get("LLM_PROVIDER") == "nebius" else os.environ.get("REASONING_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")),
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        t0 = time.time()
        try:
            if a.bench == "insightbench":
                con, tables = IB.connect(t, t["_root"])
                res = IB.SYSTEMS[s](t, con, tables, m)
                sys_meter = m.snapshot()
                jm = None if a.no_judge else Meter(10 if not a.judge_insights else 200, a.offline)
                rec["scores"] = IB.score(t, res, jm, a.judge_insights)
                if not [x for x in (t.get("insights") or []) if str(x).strip()]:  # fix (audit #3): flag-36 has 5 EMPTY strings, not []
                    rec["scores"]["excluded"] = "empty ground-truth insights in the dataset"
                rec["explain"] = EX.insight_metrics(res)
                if jm and a.faith_sample and order[t["id"]] < a.faith_sample:
                    jm.max_calls += 1
                    rec["explain"]["faithfulness"] = EX.faithfulness(jm, res)
                rec["judge_meter"] = jm.snapshot() if jm else None
                rec["judge_model"] = JUDGE_MODEL if jm else None
            else:
                res = TQ.SYSTEMS[s](t, m)
                sys_meter = m.snapshot()
                d = FIX / "tatqa" if a.fixtures else DATA / "tatqa"
                ctx = TQ.context(t["doc"])
                rec["scores"] = {"traceable": TQ.traceable(str(res.get("answer")), ctx),
                                 "numeric_answer": bool(TQ.nums(str(res.get("answer"))))}
                if (d / "tatqa_metric.py").exists():
                    rec["scores"]["em"], rec["scores"]["f1"] = TQ.item_em(d, t, res)
                    rec["scores"]["em_raw"], rec["scores"]["f1_raw"] = TQ.item_em(d, t, res["raw"])
                rec["explain"] = EX.tat_metrics(res, ctx)
                rec["gold"] = {"answer": t["q"]["answer"], "scale": t["q"]["scale"], "answer_type": t["q"]["answer_type"], "answer_from": t["q"]["answer_from"]}
            rec["output"], rec["meter"] = res, sys_meter
            # fix (audit #4): "model" is the configured default; models_used is what was actually called (Super on routed items)
            rec["models_used"] = dict(sys_meter.get("providers") or {})
            rec["question"] = (t.get("metadata") or {}).get("goal") if a.bench == "insightbench" else t["q"]["question"]  # audit trace
            rec["code_rev"] = os.popen("git rev-parse --short HEAD 2>/dev/null").read().strip() or None
        except NebiusHardStop as e:
            print(f"HARD STOP (NEBIUS_STRICT=1): {e}; item not recorded, rerun to resume")
            break
        except BudgetExceeded as e:
            rec["error"], rec["meter"] = f"BudgetExceeded: {e}", m.snapshot()
        except Exception as e:
            rec["error"], rec["meter"] = f"{type(e).__name__}: {str(e)[:300]}", m.snapshot()
            rec["trace"] = traceback.format_exc()[-800:]
        rec["seconds"] = round(time.time() - t0, 2)
        total += m.calls + ((rec.get("judge_meter") or {}).get("calls") or 0)
        full = [c.pop("prompt_full", None) for c in ((rec.get("meter") or {}).get("trace_calls") or [])]
        with out.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")  # results row keeps truncated prompts only
        if not a.no_trace:
            try:
                from .audit_trace import write_item_trace
                for c, fp in zip((rec.get("meter") or {}).get("trace_calls") or [], full):
                    if fp:
                        c["prompt_full"] = fp
                write_item_trace(rec, out, DATA if not a.fixtures else FIX, Path(a.trace_dir))
            except Exception as e:  # a trace failure must not lose the scored row; logged
                print(f"  TRACE ERROR {type(e).__name__}: {str(e)[:120]}")
        sc = rec.get("scores") or {}
        print(f"  {s:6s} {t['id'][:36]:36s} {rec['seconds']:6.1f}s calls={m.calls} {'ERR ' + rec['error'][:80] if rec.get('error') else json.dumps(sc)}")
    print(f"total model calls this run: {total}")
    if not a.offline and os.environ.get("NEBIUS_API_KEY"):
        from .nebius import status
        print(f"nebius ledger (cumulative, all processes): {json.dumps(status())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
