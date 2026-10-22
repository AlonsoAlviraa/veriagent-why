"""The model can prioritise and be stricter, but cannot override computed evidence (dev live failures, 22 Oct)."""
from app.agents.core import Planner


class Mem:
    def add_node(self, *a, **k): pass


class Ctx:
    def __init__(self, ans): self.ans = ans
    def attempt(self, agent, fn, *a, **k): return self.ans


def test_planner_keeps_rivals_when_model_drops_them():
    hyps = Planner().plan({"query": "why did on-time drop?"}, Mem(), None, Ctx(["H_region"]))
    ids = [h["id"] for h in hyps]
    assert ids[0] == "H_region" and "H_promo" in ids and "H_seasonal" in ids
