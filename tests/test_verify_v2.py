import json
from bench import verify2 as V, nebius, tatqa as TQ, insightbench as IB
from bench.run import main


def test_same_answer_numeric_and_text():
    assert V.same_answer("15.99", 15.994)
    assert not V.same_answer("15.99", "-15.99")
    assert not V.same_answer("10", "10", "million", "thousand")
    assert V.same_answer(["A", "B"], ["b", "a"])


def test_sampling_restores_temperature():
    assert nebius.TEMPERATURE == 0.0
    with V.sampling(0.7):
        assert nebius.TEMPERATURE == 0.7
    assert nebius.TEMPERATURE == 0.0


def test_cr_conf_uses_train_map():
    V.CR_CONF_MAP = [[0.5, 0.2], [1.0, 0.8]]
    try:
        assert V.cr_conf(0.9, True) == 0.8 and V.cr_conf(0.9, False) == 0.2 and V.cr_conf(None, True) == 0.2
    finally:
        V.CR_CONF_MAP = None


def test_registered():
    for s in ("agent_pot", "agent_sc", "agent_cr"):
        assert s in TQ.SYSTEMS and s in IB.SYSTEMS


def test_offline_runs_write_traces(tmp_path):
    for b in ("tatqa", "insightbench"):
        out = tmp_path / f"{b}.jsonl"
        assert main(["--bench", b, "--offline", "--fixtures", "--systems", "agent_pot,agent_sc,agent_cr", "--limit", "1",
                     "--out", str(out), "--trace-dir", str(tmp_path / "tr")]) == 0
        rows = [json.loads(l) for l in out.read_text().splitlines()]
        assert len(rows) == 3 and all(not r.get("error") and r["output"]["v2"]["strategy"] for r in rows)
        assert (tmp_path / "tr" / b / "audit_index.jsonl").exists()
