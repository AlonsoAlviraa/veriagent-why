"""Evaluation protocol (external review P0-1/P0-2): dirty-tree abort, per-row provenance, frozen disjoint held-out."""
import hashlib, json
from pathlib import Path
import pytest
from bench import run as R

SPL = Path(__file__).resolve().parents[1] / "bench" / "splits"


def test_live_run_aborts_on_dirty_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "git_state", lambda: {"code_rev": "abc1234", "code_rev_full": "abc1234" * 5, "dirty": True, "dirty_files": ["x.py"]})
    with pytest.raises(SystemExit, match="dirty"):
        R.main(["--bench", "tatqa", "--systems", "agent", "--limit", "1", "--out", str(tmp_path / "o.jsonl")])


def test_rows_record_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "git_state", lambda: {"code_rev": "abc1234", "code_rev_full": "f" * 40, "dirty": False, "dirty_files": []})
    out = tmp_path / "o.jsonl"
    R.main(["--bench", "tatqa", "--systems", "agent", "--limit", "1", "--offline", "--fixtures", "--no-trace", "--repeat", "2", "--out", str(out)])
    row = json.loads(out.read_text().splitlines()[0])
    for k in ("code_rev", "code_rev_full", "dirty", "split", "seed", "model", "repeat"):
        assert k in row, k
    assert row["dirty"] is False and row["repeat"] == 2 and row["split"]["name"] == "fixture" and row["split"]["data_sha256"]


def test_holdout_frozen_and_disjoint_from_contaminated():
    h = json.loads((SPL / "holdout_v1.json").read_text())
    c = json.loads((SPL / "contaminated.json").read_text())
    assert len(h["ids"]) == 100 == len(set(h["ids"])) and h["tatqa_split"] == "test_gold"
    assert hashlib.sha256("\n".join(h["ids"]).encode()).hexdigest() == h["ids_sha256"]
    assert not set(h["ids"]) & set(c["tatqa"]["dev_ids_touched"])
    assert not set(h["ids"]) & set(c["tatqa_test_gold_ids_seen_in_artifacts"])
    assert c["insightbench"]["n"] == 100  # every IB task is development data


def test_calibration_never_fit_on_holdout():
    h = set(json.loads((SPL / "holdout_v1.json").read_text())["ids"])
    calib = Path(__file__).resolve().parents[1] / "bench" / "calib"
    for f in calib.glob("*.json"):
        assert not (h & set(f.read_text().split('"'))), f
