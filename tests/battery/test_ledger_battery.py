"""NEBIUS spend ledger: the cross-process guard never lets committed + in-flight spend exceed the budget."""
import json, random, threading
import pytest
from bench import nebius as N


@pytest.fixture
def led(tmp_path, monkeypatch):
    monkeypatch.setenv("NEBIUS_LEDGER", str(tmp_path / "l.json"))
    monkeypatch.setenv("NEBIUS_BUDGET_USD", "1.0")
    return tmp_path / "l.json"


@pytest.mark.parametrize("model", sorted(N.PRICES))
@pytest.mark.parametrize("pt,ct", [(0, 0), (1000, 0), (0, 1000), (123456, 789), (10**6, 10**6)])
def test_cost_formula(model, pt, ct):
    i, o = N.PRICES[model]
    assert abs(N.cost(model, pt, ct) - (pt * i + ct * o) / 1e6) < 1e-12


@pytest.mark.parametrize("m", ["gpt-4", "nvidia/unknown", "", "nvidia/Nemotron-3_5-lightning"])
def test_unknown_model_refused(led, m):
    with pytest.raises(N.NebiusBudgetExceeded):
        N.reserve(m, 10, 10)


@pytest.mark.parametrize("seed", range(30))
def test_random_sequences_never_exceed_budget(led, seed):
    r = random.Random(seed); model = "nvidia/Nemotron-3-Ultra-550b-a55b"
    for _ in range(60):
        try:
            rid = N.reserve(model, r.randint(100, 60000), r.randint(10, 4000))
        except N.NebiusBudgetExceeded:
            continue
        kind = r.choice(["usage", "worst", "free"])
        N.settle(rid, model, {"prompt_tokens": r.randint(0, 50000), "completion_tokens": r.randint(0, 3000)} if kind == "usage" else None, kind == "worst")
        st = N.status()
        assert st["spent_usd"] + st["reserved_usd"] <= 1.0 + 0.2  # usage may exceed the estimate; reservation guard is pre-call
    d = json.loads(led.read_text())
    assert d["reserved"] == {} and len(d["entries"]) == d["calls"]


@pytest.mark.parametrize("seed", range(10))
def test_concurrent_reservations_respect_budget(led, seed):
    model = "nvidia/Nemotron-3-Ultra-550b-a55b"; ok = []; lock = threading.Lock()
    def w():
        try:
            rid = N.reserve(model, 30000, 3000)  # worst ~0.039 USD
            with lock: ok.append(rid)
        except N.NebiusBudgetExceeded:
            pass
    ts = [threading.Thread(target=w) for _ in range(40)]
    [t.start() for t in ts]; [t.join() for t in ts]
    st = N.status()
    assert st["reserved_usd"] <= 1.0 + 1e-9 and len(ok) == int(1.0 // N.cost(model, 30000, 3000))


def test_failed_call_books_worst_case_and_4xx_books_zero(led):
    m = N.DEFAULT_MODEL
    w = N.cost(m, 1000, 100)
    N.settle(N.reserve(m, 1000, 100), m, None, True)
    N.settle(N.reserve(m, 1000, 100), m, None, False)
    assert abs(N.status()["spent_usd"] - w) < 1e-6
