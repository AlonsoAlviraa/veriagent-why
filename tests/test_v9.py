"""Offline unit tests for V9 (no network, no writes to bench/results)."""
import math
from bench import v9


def _lp(tokens):
    return [{"t": t, "lp": l, "top": [[t, l], ["x", l - 1.0]]} for t, l in tokens]


def test_lp_features_answer_span():
    lp = _lp([('{"', -0.01), ('answer', -0.01), ('":', -0.01), (' "', -0.01), ('12', -0.5), ('.5', -0.2), ('",', -0.01),
              (' "scale', -0.01), ('":', -0.01), (' ""', -0.9), ('}', -0.01)])
    f = v9.lp_features(lp, "")
    assert f["lp_ok"] and f["n_ans_tok"] == 2
    assert math.isclose(f["ans_min_lp"], -0.5) and math.isclose(f["ans_msp"], math.exp(-0.7))
    assert f["ans_min_margin"] is not None


def test_lp_features_missing():
    assert v9.lp_features(None) == {"lp_ok": False}


def test_ptrue_renormalises():
    lp = [{"t": '{"verdict": "', "lp": 0, "top": []}, {"t": "A", "lp": math.log(0.6), "top": [["A", math.log(0.6)], ["B", math.log(0.2)]]}]
    f = v9.ptrue_from(lp, {"verdict": "A", "confidence": 90})
    assert math.isclose(f["ptrue"], 0.75) and f["verbal"] == 0.9


def test_ptrue_fallback_no_lp():
    assert v9.ptrue_from(None, {"verdict": "B", "confidence": "x"})["ptrue"] == 0.0


def test_sc_features_ties_keep_v7():
    f = v9.sc_features("a", ["b", "a", "b"])
    assert f["sc_pick"] == "a" and f["n_clusters"] == 2
    f = v9.sc_features("a", ["b", "b", "b"])
    assert f["sc_pick"] == "b" and f["sample_agree_v7"] == 0
    assert v9.sc_features("a", ["a", "a", "a"])["sem_entropy"] == 0


def test_logprobs_context_restores():
    from bench import nebius
    assert nebius.LOGPROBS is False
    with v9.logprobs():
        assert nebius.LOGPROBS is True
    assert nebius.LOGPROBS is False


def test_akey_normalises_numbers():
    assert v9.akey("1,000.0", "million") == v9.akey("1000", "million")


def test_duplicate_top_tokens_deduped():
    x = {"t": "A", "lp": math.log(0.9), "top": [["A", math.log(0.9)], ["A", math.log(0.9)], [" A", math.log(0.05)], ["B", math.log(0.05)], ["", -9999.0]]}
    f = v9.ptrue_from([x], {"verdict": "A"})
    assert math.isclose(f["ptrue"], 0.95 / 1.0)
    g = v9.lp_features([{"t": "5", "lp": math.log(0.9), "top": x["top"]}])
    assert math.isclose(g["ans_min_margin"], 0.85)


def test_crc_controls_risk_offline():
    from bench.v9_report import crc
    y = [1] * 70 + [0] * 30
    s = [0.9] * 70 + [0.1] * 30
    fo = [list(range(i, 100, 5)) for i in range(5)]
    o = crc(s, y, fo, alpha=0.1)
    assert o["realized_risk_answered_and_wrong"] <= 0.1 and o["coverage"] == 0.7


def test_gfolds_table_disjoint():
    import json
    import pytest
    from pathlib import Path
    if not Path("data/bench/tatqa/tatqa_dataset_train.json").exists():
        pytest.skip("TAT-QA train not downloaded (data/bench is gitignored)")
    from bench.v9_report import gfolds, table_of
    ids = json.load(open("docs/v9/design.json"))["ids"][:120]
    t = table_of(); fo = gfolds(ids)
    tabs = [{t[ids[n]] for n in f} for f in fo]
    assert sum(len(f) for f in fo) == len(ids)
    assert all(not (tabs[a] & tabs[b]) for a in range(5) for b in range(a + 1, 5))
