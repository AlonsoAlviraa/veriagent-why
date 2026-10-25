"""Dev-split scenarios only (q25 seasonality, q27 promotion effect)."""
import json, subprocess, sys
from pathlib import Path
import pytest
from app.pipeline import run

R = Path(__file__).parents[1]
QS = {q["qid"]: q for q in json.loads((R / "eval" / "questions.json").read_text(encoding="utf-8"))}


@pytest.fixture(scope="module", autouse=True)
def datasets():
    if not (R / "data" / "eval" / "q27.duckdb").exists():
        subprocess.run([sys.executable, str(R / "eval" / "build_datasets.py")], check=True)


def test_seasonality_dev():
    assert QS["q25"]["split"] == "dev"
    r = run(QS["q25"]["input"], "t-q25")["output"]["result"]
    assert r["analysis"]["top_cause_label"] == "seasonality"


def test_promo_effect_beats_carrier_cell_dev():
    assert QS["q27"]["split"] == "dev"
    r = run(QS["q27"]["input"], "t-q27")["output"]["result"]
    assert r["analysis"]["top_cause_label"] == "promotion_effect"
