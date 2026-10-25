"""Markovian control (bench/markov.py): deterministic decisions, each logged with state + reason + carryover."""
import json
from bench import markov as MK
from bench import run as R


def test_route_numeric_vs_evidence_and_logged():
    c = MK.Controller()
    assert c.route("What is the percentage change in revenue from 2018 to 2019?")["path"] == "NUMERIC"
    assert c.route("Which segment had the highest revenue?")["path"] == "EVIDENCE"
    for d in c.log:
        assert d["decision"] == "route" and d["reason"] and d["carryover"].startswith("[STATE_CHECKPOINT]")


def test_route_deep_only_with_nv_features():
    nv = {"x": {"task_type_1": "Open QA", "prompt_complexity_score": 0.2, "reasoning": 0.01}}
    q = "What is the average revenue?"
    assert MK.Controller(False, nv).route(q, "x")["deep"] is False
    r = MK.Controller(True, nv).route(q, "x")
    assert r["deep"] and r["model"] == MK.DEEP_MODEL
    assert MK.Controller(True, nv).route("Which year is it?", "x")["deep"] is False  # deep only on numeric path


def test_gate_retry_expected_gain():
    c = MK.Controller()
    assert not c.gate_retry([], 0, True)
    assert c.gate_retry(["evidence not found in context: foo"], 0, True)  # fix B1: quote rejection retries (gain 0.4)
    assert c.gate_retry(["answer 3 != expression value 4"], 0, False)
    assert not c.gate_retry(["answer 3 != expression value 4"], 1, False)  # round cap
    assert [d["action"] for d in c.log] == ["ACCEPT", "RETRY", "RETRY", "STOP"]


def test_sql_repair_policy():
    c = MK.Controller()
    assert c.sql_repair("ERROR BinderException: Binder Error: column x not found", 0, None)
    assert not c.sql_repair("ERROR BinderException: Binder Error: column x not found", 1, "ERROR BinderException: Binder Error: column x not found")
    assert c.sql_repair("ERROR OutOfMemoryException: boom", 0, None)  # fix B7: unknown class gets one repair
    assert not c.sql_repair("ERROR OutOfMemoryException: boom", 1, None)
    assert not c.sql_repair("ERROR Parser Error: x", 2, None)


def test_requery_and_rewrite():
    c = MK.Controller()
    assert not c.requery(0, 6, 0, 6, 3)  # sufficient -> evaluator skipped
    assert c.requery(0, 2, 2, 2, 3)
    assert not c.requery(1, 2, 2, 0, 3)  # no new evidence
    assert not c.requery(1, 2, 2, 1, 2)  # cap
    assert not c.rewrite(8, 1, False, 0, None, 2)  # drop instead of rewrite
    assert c.rewrite(4, 3, False, 0, None, 2)
    assert not c.rewrite(4, 3, False, 1, 3, 2)  # no improvement


def test_determinism():
    a, b = MK.Controller(), MK.Controller()
    for c in (a, b):
        c.route("What is the total change?"); c.gate_retry(["expression number 7 not in context"], 0, False)
    # Each entry carries a wall-clock "t" (audit ordering); it may differ by 1 ms
    # between the two controllers, so compare everything except that field.
    assert a.log and all("t" in d for d in a.log + b.log)
    strip = lambda log: [{k: v for k, v in d.items() if k != "t"} for d in log]
    assert json.dumps(strip(a.log), sort_keys=True) == json.dumps(strip(b.log), sort_keys=True)


def test_offline_systems_log_decisions(tmp_path):
    for bench in ("tatqa", "insightbench"):
        out = tmp_path / f"{bench}.jsonl"
        R.main(["--bench", bench, "--offline", "--fixtures", "--systems", "agent_mk,agent_mknv", "--out", str(out), "--no-judge"])
        recs = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        assert recs and all(not r.get("error") for r in recs)
        assert all(r["output"]["decisions"] for r in recs)


def test_evidence_check_rerank_decision():
    c = MK.Controller()
    assert not c.evidence_check(None, 0, True)
    assert not c.evidence_check(0.9, 0, True)
    assert c.evidence_check(MK.RELEVANCE_MIN / 2, 0, True)  # threshold calibrated on TAT-QA train
    assert not c.evidence_check(MK.RELEVANCE_MIN / 2, 1, True)  # cap -> FLAG
    assert [d["action"] for d in c.log] == ["NO_SIGNAL", "ACCEPT", "RETRY", "FLAG"]
