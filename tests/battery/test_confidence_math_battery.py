"""Confidence / abstention math battery: AUROC, AURC, ECE, conformal risk control (CRC) and the frozen V7 lex rule,
checked against brute-force definitions on generated data."""
import math, random
import pytest
from bench.heldout_report import auroc, aurc, ece
from bench.v9_final import crc_lambda
from bench.abstention import signal, answers, THRESHOLD, selective


def gen(seed, n=None, ties=False):
    r = random.Random(seed); n = n or r.randint(8, 120)
    y = [r.random() < r.uniform(0.2, 0.8) for _ in range(n)]
    s = [round(r.random(), 1 if ties else 6) for _ in range(n)]
    return y, s


def brute_auroc(y, s):
    P = [c for c, t in zip(s, y) if t]; N = [c for c, t in zip(s, y) if not t]
    if not P or not N: return None
    w = 0.0
    for p in P:
        for q in N: w += 1 if p > q else 0.5 if p == q else 0
    return w / len(P) / len(N)


SEEDS = range(150)


@pytest.mark.parametrize("seed", SEEDS)
def test_auroc_matches_bruteforce_and_symmetries(seed):
    y, s = gen(seed, ties=seed % 2 == 0)
    a = auroc(y, s); b = brute_auroc(y, s)
    if b is None:
        assert a is None; return
    assert abs(a - b) < 1e-12 and 0 <= a <= 1
    assert abs(auroc(y, [-x for x in s]) - (1 - a)) < 1e-12           # reversing the score flips AUROC
    assert abs(auroc(y, [3 * x + 7 for x in s]) - a) < 1e-12          # invariant to monotone transforms
    assert abs(auroc(y, [0.5] * len(y)) - 0.5) < 1e-12                # constant score = coin


@pytest.mark.parametrize("seed", SEEDS)
def test_aurc_bounds_and_oracle(seed):
    y, s = gen(seed)
    v = aurc(y, s); err = 1 - sum(y) / len(y)
    assert 0 <= v <= 1
    oracle = aurc(y, [1.0 if t else 0.0 for t in y])
    worst = aurc(y, [0.0 if t else 1.0 for t in y])
    assert oracle <= v + 1e-12 <= worst + 2e-12
    assert abs(aurc(y, [0.5] * len(y)) - sum((sum(1 - t for t in y[:k]) / k) for k in range(1, len(y) + 1)) / len(y)) < 1e-12
    assert oracle <= err + 1e-12


@pytest.mark.parametrize("seed", SEEDS)
def test_ece_bounds_and_perfect(seed):
    y, s = gen(seed)
    e = ece(y, s)
    assert 0 <= e <= 1
    assert ece(y, [float(t) for t in y]) < 1e-12               # confident and right/wrong exactly
    p = sum(y) / len(y)
    assert ece(y, [p] * len(y)) < 1e-9                        # constant = base rate is calibrated


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("alpha", [0.05, 0.1, 0.2])
def test_crc_threshold_controls_calibration_risk(seed, alpha):
    y, s = gen(seed, n=200)
    lam = crc_lambda(s, y, alpha)
    ans = [t for a, t in zip(s, y) if a >= lam]
    loss = sum(1 for t in ans if not t)
    assert (loss + 1) / (len(y) + 1) <= alpha + 1e-12
    # minimality: the next lower candidate violates the bound (unless lam is the smallest score)
    cands = sorted(set(s))
    lower = [c for c in cands if c < lam]
    if lower:
        l2 = lower[-1]
        loss2 = sum(1 for a, t in zip(s, y) if a >= l2 and not t)
        assert (loss2 + 1) / (len(y) + 1) > alpha


@pytest.mark.parametrize("seed", range(40))
def test_crc_infinite_when_infeasible(seed):
    """alpha < 1/(m+1) is infeasible even when abstaining on everything. The raw bench.v9_final.crc_lambda raises
    StopIteration there; the analysis wrapper (bench.v9_gen_analysis.crc_lambda, used for V9.1/V10) maps it to inf
    = abstain on all. Finding documented in docs/TEST_BATTERY_REPORT.md."""
    from bench.v9_gen_analysis import crc_lambda as wrapped
    r = random.Random(seed); m = r.randint(10, 40)
    y = [r.random() < .5 for _ in range(m)]; s = [r.random() for _ in y]
    assert wrapped(s, y, 0.5 / (m + 1)) == math.inf
    with pytest.raises(StopIteration):
        crc_lambda(s, y, 0.5 / (m + 1))
    assert wrapped([0.9] * m, [False] * m, 0.2) == math.inf


GRID = [(det, raw) for det in (None, 0, 0.5, 0.79, 0.8, 0.81, 1.0) for raw in (None, 0, 0.9, 8, 89, 90, 91, 100, "x")]


@pytest.mark.parametrize("det,raw", GRID)
def test_lex_signal_and_frozen_threshold(det, raw):
    o = {"confidence_det": det, "confidence": raw}
    d = det if isinstance(det, (int, float)) else 0.0
    r = raw if isinstance(raw, (int, float)) else 0.0
    assert abs(signal(o) - (d + r / 100)) < 1e-12
    assert answers(o) == (d + r / 100 >= THRESHOLD - 1e-9)
    assert THRESHOLD == 0.809


@pytest.mark.parametrize("seed", range(40))
def test_selective_report_consistency(seed):
    r = random.Random(seed)
    rows = [{"output": {"confidence_det": r.choice([0.5, 0.8, 1.0]), "confidence": r.choice([50, 90, 95])}, "ok": r.random() < .6}
            for _ in range(r.randint(5, 60))] + [{"error": "x", "output": {}}]
    out = selective(rows, lambda x: float(x["ok"]))
    ok = [x for x in rows if not x.get("error")]
    assert out["n"] == len(ok) and out["answered"] == sum(answers(x["output"]) for x in ok)
    assert out["risk_coverage_curve"][-1][0] == 1.0
    assert abs(out["risk_coverage_curve"][-1][1] - (1 - sum(x["ok"] for x in ok) / len(ok))) < 1e-4
