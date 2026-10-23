"""bench/audit_trace.py: builds explainable per-case traces from result rows; never invents data."""
import json
from pathlib import Path

import pytest

from bench import audit_trace as AT

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "docs" / "audit_trace.schema.json").read_text())


def tat_row(**kw):
    r = {"bench": "tatqa", "system": "agent_mk", "id": "u1", "model": "nvidia/Nemotron-3_5-Lightning", "provider": "nebius",
         "ts": "2026-10-23T17:00:00+0200",
         "scores": {"traceable": True, "em": 0.0, "f1": 0.0, "em_raw": 0.0, "f1_raw": 0.0},
         "gold": {"answer": ["1,758"], "scale": "thousand", "answer_type": "span", "answer_from": "table"},
         "output": {"answer": "1758", "scale": "", "expression": "1758", "raw": {"answer": "1758.0", "scale": "", "expression": "1758"},
                    "evidence": ["Total | $1,758"], "confidence": 1.0, "gate_passed": False, "confidence_det": 0.2,
                    "gate": [{"round": 0, "reasons": ["evidence not found in context: Total | $1,758"]}],
                    "route": {"path": "EVIDENCE", "deep": False, "model": None},
                    "decisions": [{"decision": "route", "state": {"numeric_cue": False}, "action": "EVIDENCE", "reason": "no computation cue", "carryover": "x"},
                                  {"decision": "gate", "state": {"gate_round": 0}, "action": "STOP", "reason": "expected gain 0.1 < 0.25", "carryover": "y"}]},
         "meter": {"calls": 1, "prompt_tokens": 600, "completion_tokens": 60, "model_seconds": 0.7, "nebius_usd": 5e-05, "errors": 0,
                   "providers": {"nebius:nvidia/Nemotron-3_5-Lightning": 1}, "finish_reasons": ["stop"]}}
    r.update(kw)
    return r


def ib_row():
    return {"bench": "insightbench", "system": "agent_mk", "id": "flag-x", "model": "m", "provider": "nebius",
            "scores": {"insight_rouge1": 0.2, "summary_judge": 0.3},
            "output": {"insights": ["A is 5"], "claims": [{"text": "A is 5", "evidence": ["q1"]}], "summary": "s",
                       "confidence": None, "confidence_det": 0.375,
                       "dropped_claims": [{"text": "B is 9", "evidence": ["q2"], "unsupported": [9.0], "reason": "numbers not in cited results"}],
                       "gate": [{"round": 0, "insights": 2, "failed": 1, "summary_unsupported": []}],
                       "evidence_store": {"q1": "a | n\nA | 5", "q2": "ERROR: Binder Error: column x"},
                       "decisions": [{"decision": "depth", "state": {}, "action": "ROUNDS=2", "reason": "default", "carryover": ""}]},
            "meter": {"calls": 3, "providers": {"nebius:m": 3}},
            "judge_meter": {"calls": 1, "providers": {"nebius:nvidia/nemotron-3-super-120b-a12b": 1}}}


def build(row, tmp_path, fails=None):
    return AT.build(row, tmp_path / f"{row['bench']}-markov-sample.jsonl", tmp_path, fails or {})


def test_required_keys_and_eval_only(tmp_path):
    t = build(tat_row(), tmp_path)
    for k in SCHEMA["required"]:
        assert k in t
    assert "never shown" in t["case"]["eval_only"]["_label"]
    assert t["case"]["eval_only"]["gold"]["scale"] == "thousand"
    assert t["case"]["run"] == "markov-sample"
    step_types = SCHEMA["$defs"]["step"]["properties"]["type"]["enum"]
    assert all(s["type"] in step_types for s in t["steps"])
    assert [s["type"] for s in t["steps"]] == ["route_decision", "writer", "claim_gate", "post_format", "scoring"]


def test_not_logged_never_invented(tmp_path):
    t = build(tat_row(), tmp_path)
    assert t["case"]["question"] == AT.NL  # dataset absent -> not invented
    w = next(s for s in t["steps"] if s["type"] == "writer")
    assert w["prompt"] == AT.NL and w["prompt_hash"] == AT.NL
    assert w["latency_s"] == 0.7  # single-call item: meter attributed to the only step
    assert t["llm_calls"] == AT.NL


def test_post_format_before_after_and_decisions(tmp_path):
    t = build(tat_row(), tmp_path)
    pf = next(s for s in t["steps"] if s["type"] == "post_format")
    assert {"field": "answer", "before": "1758.0", "after": "1758", "rule": "tat_post.fmt_number/flatten"} in pf["outputs"]["changes"]
    g = next(s for s in t["steps"] if s["type"] == "claim_gate")
    assert g["decision"]["action"] == "STOP" and g["outputs"]["verdict"] == "REJECT"
    assert t["claims"][0]["gate_verdict"] == "REJECT"
    assert t["confidence"]["recomputed_base"] == t["confidence"]["deterministic"] == 0.2


def test_narrative_deterministic_and_failure(tmp_path):
    f = {("tatqa", "markov-sample", "agent_mk", "u1"): {"cause": "scale/format", "code": "bench/tat_post.py:infer_scale"}}
    a, b = build(tat_row(), tmp_path, f), build(tat_row(), tmp_path, f)
    assert a["narrative"] == b["narrative"]
    assert "scale/format" in a["narrative"] and "EVIDENCE" in a["narrative"]
    assert a["scores"]["failure"]["cause"] == "scale/format"


def test_insightbench_claims_evidence_confidence(tmp_path):
    t = build(ib_row(), tmp_path)
    v = {c["id"]: c for c in t["claims"]}
    assert v["c1"]["gate_verdict"] == "KEPT" and v["c1"]["traceable"] is True
    assert v["d1"]["gate_verdict"] == "DROPPED" and "9.0" in v["d1"]["why"]
    assert [e["is_error"] for e in t["evidence"]] == [False, True]
    sql = [s for s in t["steps"] if s["type"] == "sql"]
    assert sql[1]["errors"] and sql[0]["inputs"]["sql"] == AT.NL
    assert t["confidence"]["recomputed"] == t["confidence"]["deterministic"] == 0.375
    roles = {m["role"] for m in t["models"]}
    assert roles == {"generator", "judge"}


def test_hook_fields_are_used_when_present(tmp_path):
    r = ib_row()
    r["output"]["queries_log"] = {"q1": {"question": "count A", "sql": "SELECT 1", "first_error": None},
                                  "q2": {"question": "x", "sql": "SELECT x", "first_error": "ERROR: Binder Error"}}
    r["meter"]["trace_calls"] = [{"tag": "plan", "prompt_hash": "sha256:ab", "prompt": "[system] plan", "latency_s": 1.2,
                                  "prompt_tokens": 10, "completion_tokens": 5, "cost_usd": 1e-6, "model": "nebius:m"},
                                 {"tag": "write", "prompt_hash": "sha256:cd", "prompt": "[system] write", "latency_s": 2.0},
                                 {"tag": "unknown_tag", "prompt_hash": "sha256:ef"}]
    t = build(r, tmp_path)
    assert t["evidence"][0]["query"] == "SELECT 1"
    plan = next(s for s in t["steps"] if s["type"] == "plan")
    assert plan["prompt_hash"] == "sha256:ab" and plan["latency_s"] == 1.2 and plan["tokens"]["prompt"] == 10
    assert [c["tag"] for c in t["llm_calls"]] == ["unknown_tag"]


def test_secret_redaction(tmp_path):
    r = tat_row()
    r["output"]["evidence"] = ["key nvapi-ABCDEFGHIJKLMNOP123 here", "nvidia/prompt-task-and-complexity-classifier"]
    t = build(r, tmp_path)
    s = json.dumps(t)
    assert "nvapi-ABCDEF" not in s and t["secret_scan"]["redactions"] == 1
    assert "prompt-task-and-complexity-classifier" in s


@pytest.mark.parametrize("cfg,role", [("agent_mknv", "classifier"), ("agent_mkr", "reranker")])
def test_aux_models(tmp_path, cfg, role):
    t = build(tat_row(system=cfg), tmp_path)
    assert role in {m["role"] for m in t["models"]}


def test_schema_validates_if_available(tmp_path):
    js = pytest.importorskip("jsonschema")
    js.validate(build(tat_row(), tmp_path), SCHEMA)
    js.validate(build(ib_row(), tmp_path), SCHEMA)
