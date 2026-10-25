"""Dev-split robustness cases only."""
import json, subprocess, sys
from pathlib import Path
import pytest
from app.pipeline import run

R = Path(__file__).parents[1]
QS = {q["qid"]: q for q in json.loads((R / "eval" / "questions.json").read_text(encoding="utf-8"))}


@pytest.fixture(scope="module", autouse=True)
def datasets():
    if not (R / "data" / "eval" / "q36.duckdb").exists():
        subprocess.run([sys.executable, str(R / "eval" / "build_datasets.py")], check=True)


def test_multi_cause_reports_secondary_dev():
    q = QS["q31"]; assert q["split"] == "dev"
    a = run(q["input"], "t-q31")["output"]["result"]["analysis"]
    assert a["top_cause"]["segment"] == q["expected_segment"]
    assert a["secondary_cause"]["segment"] == q["expected_secondary"]["segment"]


def test_distractor_negative_is_unresolved_with_reasons_dev():
    q = QS["q34"]; assert q["split"] == "dev"
    out = run(q["input"], "t-q34")
    r = out["output"]["result"]
    assert out["status"] == "partial" and r["confidence"]["confidence"] <= 40
    assert r["unresolved_reasons"] and "Why this is unresolved" in r["memo_md"]
