"""Offline smoke for the public-benchmark harness (no network, scripted fake model)."""
import json
from bench import run, report, tatqa as TQ
from bench.common import gate_text, safe_sql, wilson
import pytest


def test_claim_gate_numbers():
    assert gate_text("Hardware has 335 incidents (67%)", ["Hardware | 335\nshare 0.67"]) == []
    assert gate_text("Hardware has 999 incidents", ["Hardware | 335"]) == [999.0]


def test_sql_guard():
    assert safe_sql("SELECT 1;") == "SELECT 1"
    for bad in ("DROP TABLE data", "SELECT 1; DELETE FROM data", "COPY data TO 'x'"):
        with pytest.raises(ValueError):
            safe_sql(bad)


def test_tatqa_gate_and_trace():
    ctx = "| Revenue | $1,200 | $1,000 |"
    assert TQ.gate({"answer": "20", "expression": "(1200-1000)/1000*100", "evidence": ["$1,200"]}, ctx) == []
    assert TQ.gate({"answer": "25", "expression": "(1200-1000)/1000*100", "evidence": []}, ctx)
    assert TQ.traceable("200", ctx) and not TQ.traceable("4321", ctx)


@pytest.mark.parametrize("bench", ["insightbench", "tatqa"])
def test_runner_offline_resumable(tmp_path, bench):
    out = tmp_path / "r.jsonl"
    args = ["--bench", bench, "--offline", "--fixtures", "--out", str(out), "--max-calls", "50"]
    assert run.main(args) == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert {r["system"] for r in rows} == {"agent", "rag", "react"} and not any(r.get("error") for r in rows)
    assert run.main(args) == 0  # resume: nothing re-run
    assert len(out.read_text(encoding="utf-8").splitlines()) == len(rows)
    s = report.summarise(report.load(out))
    assert all(d["n"] == 1 for d in s)


def test_budget_cap(tmp_path):
    out = tmp_path / "r.jsonl"
    run.main(["--bench", "insightbench", "--offline", "--fixtures", "--out", str(out), "--max-calls", "1", "--systems", "agent"])
    r = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert r["error"].startswith("BudgetExceeded")


def test_wilson():
    assert wilson(0, 0) == (0.0, 0.0) and wilson(5, 10)[0] < 0.5 < wilson(5, 10)[1]


# ---- Nebius hard budget guard (no network) ----
def _neb(tmp_path, monkeypatch, budget="0.01"):
    from bench import nebius
    monkeypatch.setenv("NEBIUS_LEDGER", str(tmp_path / "spend.json"))
    monkeypatch.setenv("NEBIUS_BUDGET_USD", budget)
    return nebius


def test_nebius_cost_and_unknown_model(tmp_path, monkeypatch):
    nb = _neb(tmp_path, monkeypatch)
    assert abs(nb.cost("nvidia/nemotron-3-super-120b-a12b", 1_000_000, 1_000_000) - 1.20) < 1e-9
    import pytest
    with pytest.raises(nb.NebiusBudgetExceeded):
        nb.reserve("some/unpriced-model", 10, 10)


def test_nebius_budget_refuses_worst_case_and_persists(tmp_path, monkeypatch):
    nb = _neb(tmp_path, monkeypatch, "0.01")
    m = "nvidia/Nemotron-3-Ultra-550b-a55b"  # 3 $/1M out -> 2000 tok worst = 0.006
    rid = nb.reserve(m, 0, 2000)
    import pytest
    with pytest.raises(nb.NebiusBudgetExceeded):  # in-flight reservation counts
        nb.reserve(m, 0, 2000)
    nb.settle(rid, m, {"prompt_tokens": 0, "completion_tokens": 2000}, True)
    assert abs(nb.status()["spent_usd"] - 0.006) < 1e-9 and nb.status()["reserved_usd"] == 0
    with pytest.raises(nb.NebiusBudgetExceeded):
        nb.reserve(m, 0, 2000)
    nb.reserve(m, 0, 1000)  # 0.003 still fits


def test_nebius_unknown_usage_books_worst(tmp_path, monkeypatch):
    nb = _neb(tmp_path, monkeypatch, "1")
    m = "nvidia/Nemotron-3_5-Lightning"
    rid = nb.reserve(m, 1000, 1000)
    assert abs(nb.settle(rid, m, None, True) - 0.0003) < 1e-12


def test_nebius_refusal_falls_back_to_nvidia(tmp_path, monkeypatch):
    nb = _neb(tmp_path, monkeypatch, "0")
    monkeypatch.setenv("LLM_PROVIDER", "nebius")
    monkeypatch.setenv("NEBIUS_API_KEY", "dummy-not-used")
    from app import llm
    from bench import llmio
    seen = {}
    monkeypatch.setattr(llm, "complete", lambda msgs, tier, mt: seen.setdefault("r", {"provider": "nvidia", "content": "{}", "usage": {}}))
    r = llmio._live([{"role": "user", "content": "hi"}], "s2", 100)
    assert r["provider"] == "nvidia" and nb.status()["spent_usd"] == 0
    import os
    assert os.environ["LLM_PROVIDER"] == "nvidia"
