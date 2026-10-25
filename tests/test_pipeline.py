import json
from pathlib import Path
from app.pipeline import run

INP = json.loads((Path(__file__).parents[1] / "input_examples" / "example_1.json").read_text(encoding="utf-8"))["input"]


def test_end_to_end_sample():
    r = run(INP, "test-e2e")
    res = r["output"]["result"]
    assert r["status"] == "success"
    assert res["analysis"]["top_cause_label"] == "carrier_sla_breach"
    assert any(d["promo_id"] == "PROMO-HOME-SOUTH" for d in res["analysis"]["discarded"])
    assert all(c["row_ids"] for c in res["claims"])
    events = [json.loads(l)["event"] for l in (Path(__file__).parents[1] / r["log_file"]).read_text(encoding="utf-8").splitlines()]
    assert "send_back_to_planner" in events and "checked" in events


def test_hmem_invariant_every_claim_has_rows():
    res = run(INP, "test-inv")["output"]["result"]
    assert res["evidence_graph"]["edges"] > 0
    for c in res["claims"]:
        assert len(c["row_ids"]) >= 1


def test_bad_input_raises():
    import pytest
    with pytest.raises(ValueError):
        run({"query": "why?"}, "test-bad")
