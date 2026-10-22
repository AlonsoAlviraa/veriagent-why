from app.confidence import confidence


def test_formula_full():
    assert confidence(4, 4, 3, 3, 2, 0)["confidence"] == 100


def test_formula_mixed():
    # C=0.5, A=2/3, R=0.25 -> 100*(0.225+0.2333+0.15)=60.8 -> 61
    assert confidence(4, 2, 2, 3, 3, 1)["confidence"] == 61


def test_no_relevant_views_cap_50_and_A_zero():
    r = confidence(2, 2, 0, 0, 1, 0)
    assert r["A"] == 0 and r["confidence"] <= 50


def test_partial_cap_40():
    assert confidence(2, 2, 3, 3, 1, 0, partial=True)["confidence"] == 40


def test_C_counts_blocked_claims():
    assert confidence(3, 1, 1, 1, 1, 0)["C"] == round(1 / 3, 3)
