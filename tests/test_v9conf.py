import json
from pathlib import Path
import pytest
from app import v9conf

FX = json.loads((Path(__file__).parent / "fixtures/v9_full_rows.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", FX, ids=[r["uid"] for r in FX])
def test_matches_benchmark_v9_full(row):
    assert v9conf.prob(v9conf.vector(row["output"])) == pytest.approx(row["expected_p"], abs=1e-6)


def test_default_on_decision_and_receipt(tmp_path, monkeypatch):
    monkeypatch.delenv("V9_CONFIDENCE", raising=False)
    monkeypatch.setenv("VA_LOG_DIR", str(tmp_path))
    lam = v9conf.model()["crc"]["lambda"]
    for i, row in enumerate(FX):
        r = v9conf.assess(row["output"], run_id="t9", item_id=row["uid"])
        assert r["enabled"] and r["decision"] == ("answer" if row["expected_p"] >= lam else "abstain")
        assert r["answer"] == row["output"]["answer"]  # V7 answer untouched
    lines = [json.loads(l) for l in (tmp_path / "receipts-t9.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == len(FX) and all(l["kind"] == "v9_confidence" for l in lines)


def test_flag_off(monkeypatch):
    monkeypatch.setenv("V9_CONFIDENCE", "off")
    assert v9conf.assess(FX[0]["output"]) == {"enabled": False}


def test_model_reproduces_documented_holdout():
    m = v9conf.model()
    assert m["holdout_check"]["auroc"] == pytest.approx(0.816, abs=0.001)
    assert m["crc"]["lambda"] == pytest.approx(0.683, abs=0.001)
