"""Scorer battery: official TAT-QA EM/F1 (vendored tatqa_metric, downloaded by `make data`) and the declared
semantic_correct label. Generated edge cases over scales, signs, percentages, lists and rounding."""
import itertools, random, sys
from pathlib import Path
import pytest
from bench.semantic import semantic_correct, num, norm, FACT

DATA = Path(__file__).resolve().parents[2] / "data" / "bench" / "tatqa"
HAS_OFFICIAL = (DATA / "tatqa_metric.py").exists()


def official(gold_answer, gold_scale, answer_type, pred, pred_scale):
    sys.path.insert(0, str(DATA))
    import tatqa_metric
    m = tatqa_metric.TaTQAEmAndF1()
    m(ground_truth={"answer": gold_answer, "scale": gold_scale, "answer_type": answer_type, "answer_from": "table"},
      prediction=pred, pred_scale=pred_scale)
    e, f, _, _ = m.get_overall_metric()
    return e, f


rng = random.Random(2026)
VALUES = sorted({round(rng.uniform(-5000, 5000), rng.choice([0, 1, 2])) for _ in range(40)} | {0.0, 1.0, -1.0, 0.5, 100.0, -0.25})
SCALES = ["", "thousand", "million", "billion", "percent"]


@pytest.mark.parametrize("v", VALUES)
@pytest.mark.parametrize("scale", SCALES)
def test_semantic_identity(v, scale):
    ok, why = semantic_correct(str(v), scale, str(v), scale, "arithmetic")
    assert ok, why


@pytest.mark.parametrize("v", [x for x in VALUES if abs(x) > 0.02])
@pytest.mark.parametrize("scale", SCALES)
def test_semantic_sign_never_relaxed(v, scale):
    ok, _ = semantic_correct(str(-v), scale, str(v), scale, "arithmetic")
    assert not ok


@pytest.mark.parametrize("v", [x for x in VALUES if abs(x) >= 1])
@pytest.mark.parametrize("a,b", [("thousand", "million"), ("million", "billion")])
def test_semantic_scale_conversion(v, a, b):
    # 1500 thousand == 1.5 million
    ok, why = semantic_correct(str(v * 1000), a, str(v), b, "arithmetic")
    assert ok, why


@pytest.mark.parametrize("v", [x for x in VALUES if 0.05 < abs(x) < 50])
def test_semantic_ratio_vs_percent(v):
    assert semantic_correct(str(v / 100), "", str(v), "percent", "arithmetic")[0]


@pytest.mark.parametrize("v", [x for x in VALUES if abs(x) > 20])
@pytest.mark.parametrize("rel", [0.02, 0.05, 0.3])
def test_semantic_wrong_value_rejected(v, rel):
    assert not semantic_correct(str(round(v * (1 + rel), 4)), "", str(v), "", "arithmetic")[0]


@pytest.mark.parametrize("v", [x for x in VALUES if abs(x) > 20])
def test_semantic_rounding_tolerance(v):
    assert semantic_correct(str(round(v * 1.004, 4)), "", str(v), "", "arithmetic")[0]


@pytest.mark.parametrize("s,expect", [("(1,234)", -1234.0), ("$1,234.5", 1234.5), ("12%", 12.0), ("−3.5", -3.5),
                                      ("5 million", 5.0), ("abc", None), ("", None), ("1,234,567", 1234567.0)])
def test_num_parser(s, expect):
    assert num(s) == expect


SPANS = ["Goodwill", "Net revenue", "Cost of sales", "fiscal 2019", "The Americas", "operating lease liabilities"]


@pytest.mark.parametrize("g", SPANS)
@pytest.mark.parametrize("wrap", ["{}", "the {}", "{}.", "{} (as reported)", "  {}  "])
def test_semantic_span_containment(g, wrap):
    assert semantic_correct(wrap.format(g), "", g, "", "span")[0]


@pytest.mark.parametrize("g,p", list(itertools.permutations(SPANS, 2)))
def test_semantic_span_mismatch(g, p):
    assert semantic_correct(p, "", g, "", "span")[0] == (norm(g) in norm(p))


@pytest.mark.parametrize("k", range(2, 5))
@pytest.mark.parametrize("seed", range(10))
def test_semantic_multispan_order_free_and_complete(k, seed):
    r = random.Random(seed); g = r.sample(SPANS, k); p = g[:]; r.shuffle(p)
    assert semantic_correct(p, "", g, "", "multi-span")[0]
    assert not semantic_correct(p[:-1], "", g, "", "multi-span")[0]


def test_semantic_empty_and_list_for_number():
    assert not semantic_correct("", "", "5", "", "arithmetic")[0]
    assert not semantic_correct(["1", "2"], "", "3", "", "arithmetic")[0]


off = pytest.mark.skipif(not HAS_OFFICIAL, reason="official TAT-QA scorer not downloaded (make data)")


@off
@pytest.mark.parametrize("v", VALUES)
@pytest.mark.parametrize("scale", SCALES)
def test_official_em_identity(v, scale):
    assert official([str(v)], scale, "arithmetic", str(v), scale)[0] == 1.0


@off
@pytest.mark.parametrize("v", [x for x in VALUES if abs(x) >= 1])
@pytest.mark.parametrize("ps,gs", [("", "million"), ("thousand", "million"), ("million", "")])
def test_official_em_scale_mismatch_is_zero(v, ps, gs):
    """Official EM requires the scale label; this is why semantic_correct is reported next to it."""
    assert official([str(v)], gs, "arithmetic", str(v), ps)[0] == 0.0


@off
@pytest.mark.parametrize("v", [x for x in VALUES if abs(x) > 0.02])
def test_official_em_sign(v):
    assert official([str(v)], "", "arithmetic", str(-v), "")[0] == 0.0


@off
@pytest.mark.parametrize("v", [x for x in VALUES if abs(x) > 5])
def test_official_em_two_decimal_rounding(v):
    g = round(v, 2)
    assert official([str(g)], "", "arithmetic", f"{g:.4f}", "")[0] == 1.0


@off
@pytest.mark.parametrize("g", SPANS)
def test_official_span_and_f1_bounds(g):
    e, f = official([g], "", "span", g, "")
    assert e == 1.0 and f == 1.0
    e, f = official([g], "", "span", g + " and other words", "")
    assert e == 0.0 and 0.0 < f < 1.0


@off
@pytest.mark.parametrize("seed", range(12))
def test_official_multispan_order_free(seed):
    r = random.Random(seed); g = r.sample(SPANS, 3); p = g[:]; r.shuffle(p)
    assert official(g, "", "multi-span", p, "")[0] == 1.0
