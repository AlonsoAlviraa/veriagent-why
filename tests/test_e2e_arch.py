"""Diagram-to-code traceability (ARCH v6.2): one run must touch every box and arrow of the diagram.
Sample mode (offline) and the live provider path against a local mock OpenAI-compatible server."""
import json
from pathlib import Path
import pytest
from app import pipeline
from app.config import ROOT, TIMEOUTS
from tests.test_llm_mock import serve, good, live  # noqa: F401  (fixture reuse)

INP = json.loads((ROOT / "input_examples" / "example_1.json").read_text(encoding="utf-8"))["input"]
BOXES = [("orchestrator", "start"), ("orchestrator", "backend"), ("planner", "hypotheses"), ("retriever", "retrieved"),
         ("s1_filter", "filtered"), ("evidence_evaluator", "verdicts"), ("evidence_evaluator", "send_back_to_planner"),
         ("markovian", "run"), ("cause_analyst", "ranked"), ("writer", "claims"), ("claim_gate", "checked"),
         ("observability", "run_report"), ("orchestrator", "end")]


def events(res):
    return [json.loads(l) for l in (ROOT / res["log_file"]).read_text(encoding="utf-8").splitlines()]


def test_sample_run_touches_every_box_and_writes_artifacts():
    res = pipeline.run(INP, "e2e-sample")
    seen = {(e["agent"], e["event"]) for e in events(res)}
    assert [b for b in BOXES if b not in seen] == []
    for a in res["output"]["artifacts"]:
        assert (ROOT / a).exists(), a
    rep = res["output"]["result"]["run_report"]
    assert rep["provider"] == "sample" and rep["model_calls"] == {"ok": 0, "failed": 0}
    assert rep["s1_filter"]["avoided"] >= 0 and "Run report" in res["output"]["result"]["memo_md"]
    assert res["output"]["result"]["confidence"]["confidence"] <= 100


def test_live_path_calls_each_llm_box_s1_in_parallel(live):
    live(good)
    res = pipeline.run(INP, "e2e-live")
    calls = [e["data"]["call"] for e in events(res) if e["event"] == "model_call"]
    agents = {c["agent"] for c in calls if c["ok"]}
    assert {"planner", "s1_filter", "evidence_evaluator", "cause_analyst", "writer"} <= agents
    assert max(c.get("batch", 1) for c in calls if c["agent"] == "s1_filter") > 1  # one parallel batch per round
    rep = res["output"]["result"]["run_report"]
    assert rep["provider"] == "nightshift" and rep["model_calls"]["ok"] == len([c for c in calls if c["ok"]])


def test_claim_gate_loops_back_to_cause_analyst(live):
    live(lambda s: good(s) if ("plan" in s or "relevant" in s or "verify" in s or "label" in s)
         else "On-time delivery fell to 12.3% for CarrierZ.")
    res = pipeline.run(INP, "e2e-gate")
    ev = events(res)
    assert any(e["event"] == "send_back_to_cause_analyst" for e in ev)
    assert len([e for e in ev if e["event"] == "ranked"]) >= 2 and "narrative" in res["output"]["result"]["blocked_claims"]


def test_run_deadline_gives_partial_unresolved_capped(monkeypatch):
    monkeypatch.setitem(TIMEOUTS, "run_s", 0)
    res = pipeline.run(INP, "e2e-deadline")
    r = res["output"]["result"]
    assert res["status"] == "partial" and r["resolution"] == "unresolved" and r["confidence"]["confidence"] <= 40
    assert any("run timeout" in x for x in r["unresolved_reasons"]) and r["run_report"]["deadline_hit"]
    assert any(e["event"] == "deadline_hit" for e in events(res))


def test_deadline_makes_model_calls_fail_fast(monkeypatch):
    from app import llm
    monkeypatch.setenv("SAMPLE_MODE", "false"); monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    llm.set_deadline(0.0)
    try:
        with pytest.raises(TimeoutError):
            llm.complete([{"role": "user", "content": "x"}], "s1", 5)
    finally:
        llm.set_deadline(None)


def test_app_run_writes_audit_json_next_to_memo():
    res = pipeline.run(INP, "e2e-audit")
    from app.config import log_dir
    d = log_dir() / "e2e-audit"
    a = json.loads((d / "audit.json").read_text(encoding="utf-8"))
    assert (d / "memo.md").exists()
    for k in ("planner", "sql", "evidence", "requery", "cause_analyst", "writer", "claim_gate"):
        assert a["flow"][k], k
    assert a["confidence"] and "verify_retry_attempts" in a and a["secret_scan"]["redactions"] == 0 or a["secret_scan"]
