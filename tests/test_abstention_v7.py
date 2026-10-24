import json
from pathlib import Path
from bench import abstention as A

ROOT = Path(__file__).parents[1]


def test_frozen_constants_match_fit_file():
    fit = json.loads((ROOT / "bench/calib/abstention_v7.json").read_text())
    assert fit["signal"] == A.SIGNAL and abs(fit["operating_point"]["threshold"] - A.THRESHOLD) < 1e-9
    assert set(fit["inputs"]) == {"train", "dev"}  # never test500 / holdout_v1


def test_rule():
    assert A.answers({"confidence": 0.9, "confidence_det": 0.8})
    assert not A.answers({"confidence": 0.85, "confidence_det": 0.8})
    assert not A.answers({"confidence": 1.0, "confidence_det": 0.55})
    assert not A.answers({"confidence": None, "confidence_det": None})


def test_selective_curve():
    rows = [{"output": {"confidence": 1.0, "confidence_det": 0.8}, "s": 1.0},
            {"output": {"confidence": 0.5, "confidence_det": 0.2}, "s": 0.0}]
    out = A.selective(rows, lambda r: r["s"])
    assert out["answered"] == 1 and out["coverage"] == 0.5 and out["selective_em"] == 1.0
    assert out["risk_coverage_curve"] == [[0.5, 0.0], [1.0, 0.5]]
