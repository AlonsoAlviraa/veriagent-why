"""TRACE_AUDIT P1-2 regression: an empty / null / whitespace answer can never pass the traceability check.
Fixtures = every agent_v9 row with an empty answer in the V9.1 gen (70) and V10 hard (21) runs, 84 of which were logged
as gate_passed=true by the code that produced them."""
import json
from pathlib import Path
import pytest
from bench import tatqa as TQ
from bench.markov import Controller
from app.v9conf import row_decision

ROWS = [json.loads(l) for l in (Path(__file__).parent / "fixtures/empty_answers_gen_v10.jsonl").read_text().splitlines()]


def test_fixture_counts_match_audit():
    gen = [r for r in ROWS if r["source"].startswith("gen_")]
    v10 = [r for r in ROWS if r["source"].startswith("hard_")]
    assert (len(gen), sum(r["logged_gate_passed"] for r in gen)) == (70, 70)
    assert (len(v10), sum(r["logged_gate_passed"] for r in v10)) == (21, 14)


@pytest.mark.parametrize("row", ROWS, ids=[r["source"] for r in ROWS])
def test_real_empty_rows_blocked(row):
    ctx = "\n".join(row["evidence"])
    out = {"answer": row["answer"], "expression": row["expression"], "evidence": row["evidence"]}
    assert "empty answer: blocked" in TQ.gate(out, ctx)
    assert row_decision(out)["decision"] == "abstain"


@pytest.mark.parametrize("ans", [None, "", "   ", "\n\t", [], [""], [None, " "]])
def test_synthetic_empty_blocked(ans):
    assert TQ.gate({"answer": ans, "expression": "", "evidence": []}, "revenue 10 20")[0] == "empty answer: blocked"


def test_nonempty_answer_still_passes():
    assert TQ.gate({"answer": "10", "expression": "", "evidence": ["revenue 10"]}, "revenue 10 20") == []


def test_markov_kind():
    assert Controller.reason_kind("empty answer: blocked") == "empty_answer"


def test_decision_never_uses_verbal_confidence():
    d = row_decision({"answer": "5", "confidence": 0.99})
    assert d["decision"] is None and d["verbal_confidence_used"] is False


def test_decision_matches_frozen_v9_full():
    from app import v9conf
    fx = json.loads((Path(__file__).parent / "fixtures/v9_full_rows.json").read_text())
    for row in fx:
        d = row_decision(row["output"])
        if row["output"].get("answer") not in (None, ""):
            assert d["decision"] == v9conf.assess(row["output"])["decision"]
