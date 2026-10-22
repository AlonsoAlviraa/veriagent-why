"""End-to-end check of the v6.2 diagram through the real HTTP surface:
User -> UI (:8501, proxies /api) -> API (:8000) -> orchestrator -> ... -> memo MD/PDF + trace + run report.

Starts the API and the UI as subprocesses (unless --no-start), submits a question through the UI proxy,
polls the trace like the browser does, then fetches the result, the memo (MD + PDF), a claim's row
click-through and the what-if ESTIMATE. Provider and backend come from the environment / .env:
  SAMPLE_MODE=true                         offline (default)
  SAMPLE_MODE=false LLM_PROVIDER=nvidia    NVIDIA free endpoint (NVIDIA_API_KEY in env; never printed)
  SAMPLE_MODE=false ZETARIS_BACKEND=zetaris (+ ZETARIS_* vars)  data through Zetaris JDBC instead of the DuckDB snapshot
Exit code 0 only if every diagram box emitted its trace event and every artifact was served.
Usage: python scripts/e2e_live.py [--input input_examples/example_1.json] [--no-start]"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import load_dotenv  # noqa: E402

BOXES = {("planner", "hypotheses"): "Planner", ("retriever", "retrieved"): "Zetaris SQL + BM25",
         ("s1_filter", "filtered"): "S1 Filter", ("evidence_evaluator", "verdicts"): "Evidence Eval",
         ("cause_analyst", "ranked"): "Cause Analyst", ("writer", "claims"): "Writer", ("claim_gate", "checked"): "Claim Gate",
         ("markovian", "run"): "Meterless Markovian", ("observability", "run_report"): "Observability report",
         ("orchestrator", "end"): "Memo"}


def http(method, url, body=None, raw=False, timeout=30):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        return data if raw else json.loads(data)


def wait_up(url, secs=40):
    t = time.time()
    while time.time() - t < secs:
        try:
            urllib.request.urlopen(url, timeout=2); return True
        except Exception:
            time.sleep(0.5)
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="input_examples/example_1.json")
    ap.add_argument("--no-start", action="store_true")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--ui", default="http://127.0.0.1:8501")
    a = ap.parse_args(argv)
    load_dotenv()
    procs = []
    if not a.no_start:
        env = dict(os.environ, API_URL=a.api)
        procs = [subprocess.Popen([sys.executable, "run.py", "--serve"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                 subprocess.Popen([sys.executable, "run.py", "--ui"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    problems = []
    try:
        if not (wait_up(a.api + "/health") and wait_up(a.ui + "/")):
            print("API or UI did not start"); return 2
        page = http("GET", a.ui + "/", raw=True).decode()
        print(f"[UI] {a.ui} serves the page ({len(page)} bytes); requests go through {a.ui}/api -> {a.api}")
        inp = json.loads((ROOT / a.input).read_text())["input"]
        rid = f"e2e{int(time.time())}"
        print(f"[User] question: {inp.get('query', '')[:100]}")
        http("POST", a.ui + "/api/runs", {"input": inp, "run_id": rid})
        nxt, seen, t0, status = 0, set(), time.time(), "running"
        while status == "running" and time.time() - t0 < 600:
            tr = http("GET", f"{a.ui}/api/runs/{rid}/trace?since={nxt}")
            for e in tr["events"]:
                seen.add((e["agent"], e["event"]))
                if e["event"] != "model_call":
                    print(f"  +{e['ts'] - t0:6.1f}s {e['agent']:<19} {e['event']}")
            nxt, status = tr["next"], tr["status"]
            time.sleep(1)
        res = http("GET", f"{a.ui}/api/runs/{rid}")
        missing = [v for k, v in BOXES.items() if k not in seen]
        if missing:
            problems.append(f"boxes without a trace event: {missing}")
        md = http("GET", f"{a.ui}/api/memo/{rid}.md", raw=True).decode()
        try:
            pdf = http("GET", f"{a.ui}/api/memo/{rid}.pdf", raw=True)
            pdf_ok = pdf[:4] == b"%PDF"
        except Exception:
            pdf_ok = False
        if not pdf_ok:
            problems.append("memo PDF not served")
        claims = res["claims"]
        if claims and claims[0].get("row_ids"):
            rowid = claims[0]["row_ids"][0]
            try:
                http("GET", f"{a.ui}/api/rows/v_logistics/{rowid}")
                print(f"[Click-through] claim {claims[0]['id']} -> v_logistics row {rowid}: OK")
            except Exception as e:
                problems.append(f"row click-through failed: {e}")
        wi = http("POST", f"{a.ui}/api/runs/{rid}/whatif")
        rep = res["run_report"]
        print(f"[Memo] resolution={res['resolution']} top={res['analysis']['top_cause_label']} confidence={res['confidence']['confidence']}"
              f" claims={len(claims)} blocked={len(res['blocked_claims'])} md={len(md)}B pdf={'OK' if pdf_ok else 'MISSING'}")
        print(f"[What-if] {str(wi)[:120]}")
        print(f"[Report] provider={rep['provider']} calls ok/failed={rep['model_calls']['ok']}/{rep['model_calls']['failed']}"
              f" tokens={rep['tokens']['total']} wall={rep['wall_clock_s']}s cost={rep['cost']}")
        print(f"[Data] {res['evidence_graph']['backend']} graph nodes={res['evidence_graph']['nodes']} edges={res['evidence_graph']['edges']}")
    finally:
        for p in procs:
            p.terminate()
    for p in problems:
        print("PROBLEM:", p)
    print("E2E OK" if not problems else "E2E FAILED")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
