"""TAT-QA Claim Gate (bench.tatqa.gate) planted traps on real dev documents, plus pinned known limits."""
import json, sys
from pathlib import Path
import pytest
from bench.tatqa import gate, safe_eval, traceable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
DEV = ROOT / "data/bench/tatqa/tatqa_dataset_dev.json"


@pytest.fixture(scope="module")
def rep(tmp_path_factory):
    if not DEV.exists():
        pytest.skip("TAT-QA dev not downloaded")
    import tatqa_gate_traps
    out = tmp_path_factory.mktemp("g") / "r.json"
    tatqa_gate_traps.main(["--out", str(out)])
    return json.loads(out.read_text())


def test_gold_false_alarm_below_2pct(rep):
    assert rep["by_type"]["control/gold_derivation"]["rate_flagged"] < 0.02


@pytest.mark.parametrize("t", ["answer_not_expression_value", "fabricated_evidence_number"])
def test_hard_traps_always_caught(rep, t):
    assert rep["by_type"][f"trap/{t}"]["rate_flagged"] == 1.0


def test_operand_change_mostly_caught(rep):
    assert rep["by_type"]["trap/operand_changed"]["rate_flagged"] > 0.85


CTX = "TABLE\n| Revenue | 4,351 | 3,900 |\nPARAGRAPHS\n[P1] Costs were 1,200 in 2019."


@pytest.mark.parametrize("expr,val", [("4351 - 3900", 451), ("4,351 - 3,900", 451), ("(4351 - 3900) / 3900 * 100", 11.564),
                                      ("abs(3900 - 4351)", 451), ("4351 + 3900 = 8251", 8251), ("$4,351 - $3,900", 451),
                                      ("4351 \u2212 3900", 451), ("round(4351 / 3900)", 1.12)])
def test_safe_eval(expr, val):
    assert abs(safe_eval(expr) - val) < 0.01


@pytest.mark.parametrize("expr", ["__import__('os')", "open('x')", "4351 ** 3900", "[1,2]", "x + 1", "4351, 3900", "lambda: 1"])
def test_safe_eval_rejects(expr):
    with pytest.raises(Exception):
        safe_eval(expr)


@pytest.mark.parametrize("out,ok", [
    ({"answer": "451", "expression": "4351 - 3900", "evidence": ["Revenue | 4,351 | 3,900"]}, True),
    ({"answer": "451", "expression": "4351 - 3900", "evidence": ["Revenue 4351"]}, True),
    ({"answer": "4351", "expression": "", "evidence": []}, True),
    ({"answer": "452", "expression": "4351 - 3900", "evidence": []}, True),  # within 0.6% tolerance
    ({"answer": "500", "expression": "4351 - 3900", "evidence": []}, False),
    ({"answer": "451", "expression": "4351 - 3800", "evidence": []}, False),
    ({"answer": "451", "expression": "4351 - 3900", "evidence": ["Revenue | 4,352"]}, False),
    ({"answer": "451", "expression": "4351 -", "evidence": []}, False),
    ({"answer": "11.56", "expression": "(4351 - 3900) / 3900", "evidence": []}, True),  # ratio vs percent accepted
])
def test_gate_cases(out, ok):
    assert (not gate(out, CTX)) == ok


@pytest.mark.xfail(strict=True, reason="DECISION/BUG: safe_eval strips '%' so '15%' evaluates as 15, not 0.15 -> gold derivations "
                                       "like '(1-15%)*(2.2/15%)' are flagged (3 of 6 dev false alarms)")
def test_percent_literal_in_expression():
    assert abs(safe_eval("(1-15%)*(2.2/15%)") - 12.4667) < 0.01


@pytest.mark.xfail(strict=True, reason="DECISION: mixed scale words ('60.3 million + 32,137 thousand') are stripped, not applied")
def test_scale_words_applied():
    assert abs(safe_eval("60.3 million + 32,137 thousand") - 92_437_000) < 1


@pytest.mark.xfail(strict=True, reason="DECISION/WEAKNESS: traceable() accepts nearly any number when the context has many "
                                       "numbers (all pairwise +,-,*,/ over up to 120 numbers); only ~17% of fabricated answers caught")
def test_traceable_rejects_fabricated_number_in_dense_context():
    ctx = " ".join(str(x) for x in range(101, 221, 1))
    assert not traceable("9137.17", ctx)
