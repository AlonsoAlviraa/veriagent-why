"""Regression tests for the trace-audit fixes (open-agent-hackathon/trace_audit/REPORT.md). Every fixture is copied
from a real audit trace (path in the comment) so the exact failure cannot come back silently. Offline, no network."""
import json
from pathlib import Path

import pytest

from bench.insightbench import gate_ib_claim
from bench import fixes as FX, llmio, markov
from bench.markov import Controller

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- fixtures from real traces
# tatqa-v2-agent_cr/agent_cr/ec290759-...: cr revised the gold full span into this truncation (the only cr loss)
EC29_FULL = "increases in direct labor and subcontractor costs consistent with the rate of growth in Technology Development segment revenues."
EC29_TRUNC = "increases in direct labor and subcontractor costs"
EC29_CTX = ("[P3] The overall increase in Technology Development segment costs was driven by increases in direct labor and subcontractor "
            "costs consistent with the rate of growth in Technology Development segment revenues.")
# insightbench-v2-agent_cr/agent_cr/flag-1: claim c1 vs its cited q3
FLAG1_Q3 = ("category | avg_resolution_days\nDatabase | 6.915912246855615\nHardware | 7.35763112758019\nInquiry / Help | 8.509473394943939\n"
            "Network | 6.222541506838688\nSoftware | 7.147711034692018")
FLAG1_C1 = ("Hardware incidents constitute 336 of 500 total incidents (67.2%), making them the dominant category, and have the longest "
            "average resolution time at 7.36 days across all categories")
FLAG1_C2 = "Inquiry / Help incidents have the highest average resolution time at 8.51 days despite representing only 32 total incidents"
# insightbench-post-agent_mk/agent_mk/flag-1: q5 returned 0 rows, controller STOPped "evidence sufficient (>=5 successful queries, 0 errors)"
FLAG1_Q5_EMPTY = "assigned_to | category | cnt\n"
# tatqa-post-agent_mk/agent_mk/06dfc869-...: the same calc 3 times
CALC_06DF = "(5798 - 3624) / 3624 * 100"
# insightbench-post-agent_mk/agent_mk/flag-34 q3: repair reproduced the same Binder error
FLAG34_SQL = ("SELECT state, AVG(CAST(EXTRACT(DAY FROM (end_date - start_date)) AS DOUBLE)) AS avg_duration_days FROM data GROUP BY state")
FLAG34_ERR = "ERROR BinderException: Binder Error: No function matches the given name and argument types 'date_part(STRING_LITERAL, BIGINT)'."


# ---------------------------------------------------------------- 1. spans
def test_truncated_revision_rejected_ec290759():
    assert FX.shorter_revision(EC29_FULL, EC29_TRUNC, EC29_CTX)
    assert FX.revision_guard({"answer": EC29_FULL}, {"answer": EC29_TRUNC}, {"doc": {}}, EC29_CTX)
    # a revision that is longer / different is allowed
    assert not FX.shorter_revision(EC29_TRUNC, EC29_FULL, EC29_CTX)
    assert not FX.shorter_revision("30", "3", EC29_CTX)  # numbers are not spans


def test_span_mode_off_and_split_years():
    assert FX.SPAN_MODE == "off"  # TRAIN replay: extension did not help (docs/TRACE_FIXES.md)
    assert FX.span_extend(EC29_TRUNC, [EC29_CTX[5:]])[1] is None
    assert FX.span_extend(EC29_TRUNC, [EC29_CTX[5:]], "end")[0].startswith(EC29_TRUNC + " consistent")
    assert FX.split_years("2019 and 2018") == (["2019", "2018"], "split_years")
    assert FX.split_years("2017, 2018 and 2019")[0] == ["2017", "2018", "2019"]
    assert FX.split_years("in 2019")[1] is None


def test_critic_prompt_never_asks_for_shortest_span():
    from bench.verify2 import CRIT_SYS
    assert "shortest" not in CRIT_SYS and "COMPLETE span" in CRIT_SYS


# ---------------------------------------------------------------- 2. empty results
def test_empty_result_is_gap_flag1():
    assert FX.is_empty_result(FLAG1_Q5_EMPTY) and not FX.usable(FLAG1_Q5_EMPTY)
    assert FX.is_empty_result("x | y\nNone | None")
    assert not FX.is_empty_result(FLAG1_Q3) and FX.usable(FLAG1_Q3)
    assert not FX.is_empty_result(FLAG34_ERR) and not FX.usable(FLAG34_ERR)


def test_requery_never_sufficient_with_empty():
    c = Controller(False, None, "insightbench")
    # flag-1: 6 results, one empty -> must NOT stop as "sufficient"
    assert c.requery(0, 5, 0, 5, 2, n_empty=1) is True
    assert c.log[-1]["action"] != "STOP" or "sufficient" not in c.log[-1]["reason"]
    c2 = Controller(False, None, "insightbench")
    assert c2.requery(0, 0, 0, 0, 2, n_empty=6) is True  # 0 usable rows -> requery
    c3 = Controller(False, None, "insightbench")
    assert c3.requery(0, 6, 0, 6, 2, n_empty=0) is False and "sufficient" in c3.log[-1]["reason"]


def test_gate_does_not_cite_empty_results():
    from bench.insightbench import gate_ib_claim, _fmt
    view = {"q1": "category | incident_count\nHardware | 336", "q5": FLAG1_Q5_EMPTY}
    un, _, _ = gate_ib_claim({"text": "There are 150 open incidents", "evidence": ["q5"]}, view)
    assert un == [150.0]
    un, _, _ = gate_ib_claim({"text": "Hardware has 336 incidents", "evidence": ["q1"]}, view)
    assert un == []
    assert "NO EVIDENCE" in _fmt({"q5": {"question": "x", "sql": "s", "result": FLAG1_Q5_EMPTY}})


# ---------------------------------------------------------------- 3. comparatives
def test_comparative_contradiction_flag1():
    bad = FX.check_comparatives(FLAG1_C1, [FLAG1_Q3])
    assert bad and bad[0]["actual"].startswith("Inquiry")
    assert FX.check_comparatives(FLAG1_C2, [FLAG1_Q3]) == []
    from bench.insightbench import gate_ib_claim
    assert gate_ib_claim({"text": FLAG1_C1, "evidence": ["q3"]}, {"q3": FLAG1_Q3})[2]


def test_ib_v2_gate_drops_contradiction():
    from bench.verify2 import _ib_gate
    kept, dropped = _ib_gate({"insights": [{"text": FLAG1_C1, "evidence": ["q3"]}]}, {"q3": FLAG1_Q3})
    assert dropped == 1 and kept == []  # the contradicted comparative never reaches the summary
    _, _, contra = gate_ib_claim({"text": FLAG1_C1, "evidence": ["q3"]}, {"q3": FLAG1_Q3})
    assert contra, "comparative contradiction must be detected"


# ---------------------------------------------------------------- 4. calibration
def test_isotonic_ties_pooled_and_monotone_after_smoothing():
    m = FX.isotonic_fit([0.05, 0.1, 0.45, 0.45, 1.0, 1.0, 1.0], [0, 0, 0, 0, 1, 0, 1])
    xs = [x for x, _ in m]
    assert len(xs) == len(set(xs)), "tied x must be pooled into one block"
    assert all(a[1] <= b[1] for a, b in zip(m, m[1:]))
    assert FX.isotonic_apply(m, 1.0) == m[-1][1]


def test_isotonic_monotone_and_train_only():
    m = FX.isotonic_fit([0.1, 0.2, 0.9, 0.95, 0.5, 0.6], [0, 1, 1, 1, 0, 1])
    ys = [y for _, y in m]
    assert ys == sorted(ys) and 0 < ys[0] and ys[-1] < 1
    assert FX.isotonic_apply(m, 0.05) <= FX.isotonic_apply(m, 0.99)
    import scripts.fit_trace_fixes as F
    with pytest.raises(AssertionError):
        F.assert_split([{"id": "dev-id"}], allowed={"train-id"})


@pytest.mark.parametrize("bench,fit_on", [("tatqa", "train"), ("insightbench", "tune")])
def test_calibration_files_declare_split(bench, fit_on):
    p = ROOT / "bench" / "calib" / f"cr_{bench}.json"
    if not p.exists():
        pytest.skip("calibration not fitted yet")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["fit_split"] == fit_on and d["n"] >= 25 and d["n"] == len(d["ids"])  # rows without p_correct are skipped
    ys = [y for _, y in d["map"]]
    assert ys == sorted(ys)
    if bench == "insightbench":
        tune = set(json.loads((ROOT / "bench/splits/insightbench_split.json").read_text(encoding="utf-8"))["tune"])
        assert set(d["ids"]) <= tune


# ---------------------------------------------------------------- 5. SQL repair
def test_sql_repair_stops_on_identical_repeat_flag34():
    c = Controller(False, None, "insightbench")
    assert c.sql_repair(FLAG34_ERR, 0, None) is True
    assert c.sql_repair(FLAG34_ERR, 1, FLAG34_ERR, repeat_sql=True) is False
    assert c.log[-1]["action"] == "GIVE_UP"
    assert FX.sql_key(FLAG34_SQL + " ;") == FX.sql_key("  " + FLAG34_SQL.replace(" FROM", "\nFROM"))


def test_repair_prompt_carries_failed_queries():
    from bench.insightbench import repair_prompt
    p = repair_prompt("ctx", ["data"], "q", FLAG34_SQL, FLAG34_ERR, [{"sql": FLAG34_SQL, "error": FLAG34_ERR}])
    assert "ALREADY FAILED" in p and FLAG34_SQL in p and "Binder" in p


# ---------------------------------------------------------------- 6. compute waste
def test_calc_step_stops_on_repeat_06dfc869():
    c = Controller(False, None, "tatqa")
    seen = set()
    assert c.calc_step(1, CALC_06DF, "59.988962", seen, None)
    seen.add(CALC_06DF)
    assert not c.calc_step(2, CALC_06DF, "59.988962", seen, "59.988962")
    assert c.log[-1]["action"] == "STOP"


def _tat_item():
    return {"id": "06dfc869-fixture", "q": {"question": "What was the percentage change in financing activities between 2018 and 2019?", "uid": "x"},
            "doc": {"table": {"table": [["", "2019", "2018", "2017"], ["Financing activities", "5,798", "3,624", "8,420"]]},
                    "paragraphs": [{"order": 1, "text": "Cash flows (in thousands)."}]}}


def test_agent_mk_max_calls_with_repeating_calc(monkeypatch):
    """06dfc869 replay: the model repeats the same calc forever. Before: 3 calc + >=1 answer calls. Now: 2 calc + 1 answer."""
    def fake(messages, tag):
        if tag == "tat_mk_calc":
            return json.dumps({"action": "calc", "input": CALC_06DF})
        return json.dumps({"answer": "59.99", "scale": "percent", "expression": CALC_06DF, "evidence": ["5,798", "3,624"]})
    monkeypatch.setattr(llmio, "fake", fake)
    from bench.tatqa import agent_markov
    m = llmio.Meter(50, offline=True)
    r = agent_markov(_tat_item(), m, False)
    assert m.calls <= 3, m.calls
    assert any(d["decision"] == "calc" and d["action"] == "STOP" for d in r["decisions"])


def test_meter_cache_identical_calls(monkeypatch):
    n = {"k": 0}

    def fake(messages, tag):
        n["k"] += 1
        return "{}"
    monkeypatch.setattr(llmio, "fake", fake)
    m = llmio.Meter(10, offline=True)
    msgs = [{"role": "user", "content": "same"}]
    m.call(msgs, "a"); m.call(msgs, "a"); m.call([{"role": "user", "content": "other"}], "a")
    assert m.calls == 2 and m.cache_hits == 1 and n["k"] == 2
    from bench import nebius
    monkeypatch.setattr(nebius, "TEMPERATURE", 0.7)  # sampling must never be cached
    m.call(msgs, "a")
    assert m.calls == 3


def test_ib_agent_mk_max_calls_offline(tmp_path):
    from bench import run
    out = tmp_path / "r.jsonl"
    assert run.main(["--bench", "insightbench", "--offline", "--fixtures", "--out", str(out), "--max-calls", "50", "--systems", "agent_mk"]) == 0
    r = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert not r.get("error")
    # plan + <=SQL repairs + <=1 evaluate per round + writer <= 3 rounds; the offline fake needs far fewer
    assert r["meter"]["calls"] <= 8


def test_tat_cr_skips_revision_when_not_used(monkeypatch):
    """Before: the critic's revision (2 calls) ran on every critiqued item even when p_correct >= threshold."""
    def fake(messages, tag):
        if tag == "v2_critic":
            return json.dumps({"p_correct": 0.9, "critique": "maybe the sign"})
        return json.dumps({"answer": "5798", "scale": "", "expression": "", "evidence": ["5,798"]})
    monkeypatch.setattr(llmio, "fake", fake)
    from bench.verify2 import tat_cr
    m = llmio.Meter(50, offline=True)
    r = tat_cr({**_tat_item(), "q": {"question": "What was financing activities in 2019?", "uid": "x"}}, m)
    assert "revision" not in r["v2"] and m.calls <= 3


# ---------------------------------------------------------------- 7. scale
def test_magnitude_and_scale_guard_pot():
    assert FX.magnitude_rewrite("1.4", "1400") and FX.magnitude_rewrite("24193", "24.193")
    assert not FX.magnitude_rewrite("59.99", "60.5")
    it = {"doc": {"table": {"table": [["(in millions)", "2019"], ["Revenue", "1,200"]]}, "paragraphs": []}}
    g = FX.revision_guard({"answer": "1200", "scale": "million"}, {"answer": "1.2", "scale": "billion"}, it, "")
    assert g and "10^k" in g
    g2 = FX.revision_guard({"answer": "1200", "scale": "million"}, {"answer": "1200", "scale": "thousand"}, it, "")
    assert g2 and "scale" in g2


# ---------------------------------------------------------------- 8. traces
def test_citations_valid_table_cells():
    from bench.explain import tat_metrics
    ctx = "TABLE\n|  | 2019 | 2018 |\n| Financing activities | 5,798 | 3,624 |\nPARAGRAPHS\n[P1] x"
    out = {"answer": "59.99", "expression": CALC_06DF, "evidence": ["Financing activities", "| 2019 | 2018 |", "Financing activities | 5,798 | 3,624", "made up"]}
    m = tat_metrics(out, ctx)
    assert m["citations_valid"] == 3 and m["citations_relevant"] == 1


def test_confidence_formula_matches_logged():
    from bench.confidence import recompute
    assert recompute("tat_det", {"gate_rounds": 1, "gate_passed": True, "traceable": True, "rerank_p": None}) == 0.8
    assert recompute("vr_score", {"vr_score": 73.3}) == 0.733  # vr flag-10 logged 0.733 but the old formula said 0.2
    assert recompute("ib_det", {"n_q": 6, "n_unusable": 1, "n_kept": 2, "n_dropped": 0}) == round(0.2 + 0.7 * 5 / 6, 3)


@pytest.mark.parametrize("bench", ["tatqa", "insightbench"])
def test_generated_traces_validate_schema(tmp_path, bench):
    """Offline run -> per-item traces -> JSON schema + trace-fix invariants (failure set, split set, formula matches)."""
    jsonschema = pytest.importorskip("jsonschema")
    from bench import run
    schema = json.loads((ROOT / "docs" / "audit_trace.schema.json").read_text(encoding="utf-8"))
    out = tmp_path / "r.jsonl"
    systems = "agent,agent_mk,agent_vr" if bench == "tatqa" else "agent,agent_mk,agent_cr"
    assert run.main(["--bench", bench, "--offline", "--fixtures", "--out", str(out), "--max-calls", "60", "--systems", systems]) == 0
    from bench.audit_trace import build
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert rows and not any(r.get("error") for r in rows)
    data = ROOT / "bench" / "fixtures"
    for r in rows:
        t = build(r, out, data, {})
        jsonschema.validate(t, schema)
        assert t["scores"]["failure"] and t["scores"]["failure"]["cause"]
        if t["confidence"].get("formula_id") not in (None, "legacy_unlogged"):
            assert t["confidence"]["matches_logged"], (r["system"], t["confidence"])
        if r["system"] == "agent" and bench == "tatqa":
            acts = [s["decision"]["action"] for s in t["steps"] if s["type"] == "claim_gate"]
            assert acts and set(acts) <= {"ACCEPT", "RETRY", "STOP"}
            assert not (acts[-1] == "STOP" and r["output"].get("gate_passed"))  # STOP never means "passed"
        if r["system"] == "agent_vr":
            assert any(s["type"] == "verify_retry_attempt" for s in t["steps"])
            assert any(m["role"] == "verifier" for m in t["models"])
        if r["system"] == "agent_cr" and bench == "insightbench":
            assert any(m["role"] == "verifier" for m in t["models"])


def test_ib_split_field():
    from bench.audit_trace import ib_split
    sp = json.loads((ROOT / "bench/splits/insightbench_split.json").read_text(encoding="utf-8"))
    assert ib_split(sp["tune"][0]) == "tune" and ib_split(sp["eval"][0]) == "eval"


# ---------------------------------------------------------------- 9. stats
def test_paired_stats():
    from bench.stats import mcnemar, paired_bootstrap
    a = [1] * 50 + [0] * 50
    b = [1] * 60 + [0] * 40
    r = paired_bootstrap(a, b)
    assert r["mean_diff"] == 0.1 and r["ci95"][0] > 0 and r["p"] < 0.05
    assert mcnemar([bool(x) for x in a], [bool(x) for x in b]) == {"b01": 10, "b10": 0, "p": 0.002}
    assert mcnemar([True], [True])["p"] == 1.0
