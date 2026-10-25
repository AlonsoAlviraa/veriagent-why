"""V8 (bench/v8.py): executor/pointer unit tests, voting, repair trigger, and the gold-deletion leakage invariant
extended to pointer + executor + self-consistency (all K samples logged)."""
import copy, json, re
import pytest
from bench import v8 as V
from tests.test_v71 import doc, it

D = doc([["(in millions)", "2019", "2018"], ["Revenue", "$1,200.5", "$1,100.0"], ["Cost", "(35)", "700"]],
        ["Revenue grew in 2019 due to higher volumes.", "Order intake represents commitments from customers."])
from bench.tatqa import context
CTX = context(D)
V7OUT = {"answer": "1200.5", "scale": "", "expression": "", "evidence": ["| Revenue | $1,200.5 | $1,100.0 |"], "answer_type": "span",
         "value": "1200.5", "quote": "$1,200.5"}


class TagM:
    """V7 calls get V7OUT; v8 pointer calls pop from ptrs (then {})."""
    def __init__(self, ptrs):
        self.ptrs, self.calls, self.tags, self.msgs = list(ptrs), 0, [], []

    def call_json(self, msgs, tag, *a, **k):
        self.calls += 1; self.tags.append(tag); self.msgs.append(json.dumps(msgs))
        if tag.startswith("v8"):
            return copy.deepcopy(self.ptrs.pop(0)) if self.ptrs else {}
        return dict(V7OUT)


ARITH = {"type": "arithmetic", "args": ["$1,100.0", "$1,200.5"], "expr": "(a1 - a0) / a0 * 100", "scale_source": "%"}


def test_execute_arithmetic_in_python():
    e = V.execute(ARITH, CTX)
    assert e["ok"] and e["answer"] == "9.14" and e["value"] == 9.14


def test_execute_rejects_arg_not_in_context():
    assert not V.execute({**ARITH, "args": ["$1,111.0", "$1,200.5"]}, CTX)["ok"]


def test_execute_negative_parentheses():
    e = V.execute({"type": "arithmetic", "args": ["(35)", "700"], "expr": "a0 + a1", "scale_source": ""}, CTX)
    assert e["ok"] and e["answer"] == "665"


@pytest.mark.parametrize("expr", ["__import__('os')", "a5 + a0", "a0 ** a1 if 1 else 0", "", "x + 1"])
def test_execute_rejects_bad_expr(expr):
    assert not V.execute({**ARITH, "expr": expr}, CTX)["ok"]


def test_span_is_literal_and_scale_only_from_literal_source():
    e = V.execute({"type": "span", "args": ["$1,200.5"], "expr": "", "scale_source": "(in millions)"}, CTX)
    assert e["answer"] == "$1,200.5" and e["scale"] == "million" and e["scale_valid"]
    e2 = V.execute({"type": "span", "args": ["$1,200.5"], "expr": "", "scale_source": "(in billions)"}, CTX)
    assert e2["ok"] and e2["scale"] == "" and not e2["scale_valid"]


def test_text_span_gets_no_scale():
    e = V.execute({"type": "span", "args": ["higher volumes"], "scale_source": "(in millions)"}, CTX)
    assert e["ok"] and e["scale"] == ""


def test_multispan_and_count():
    assert V.execute({"type": "multi-span", "args": ["2019", "2018"]}, CTX)["answer"] == ["2019", "2018"]
    assert V.execute({"type": "count", "args": ["Revenue", "Cost"]}, CTX)["answer"] == "2"


def test_span_with_two_args_invalid_and_bad_type_invalid():
    assert not V.execute({"type": "span", "args": ["2019", "2018"]}, CTX)["ok"]
    assert not V.execute({"type": "magic", "args": ["2019"]}, CTX)["ok"]


def test_key_normalizes_numbers_and_order():
    assert V.key("$1,200.50") == V.key("1200.5") and V.key(["b", "A"]) == V.key(["a", "B"])


def test_invalid_pointer_falls_back_to_v7_and_triggers_repair():
    m = TagM([{"type": "span", "args": ["not in ctx"]}] * (V.K + 1) + [{"type": "span", "args": ["$1,100.0"]}])
    o = V.agent_v8(it(copy.deepcopy(D), "What is revenue in 2018?"), m)
    assert o["v8"]["A"].get("fallback") and o["v8"]["B"].get("fallback")
    assert m.tags.count("v8_ptr_repair") == 1 and o["v8"]["BC"]["answer"] == "1100"


def test_no_repair_when_any_sample_valid_even_if_low_agreement():
    ptrs = [{"type": "span", "args": ["$1,100.0"]}] + [{"type": "span", "args": ["x"]}] * V.K
    m = TagM(ptrs)
    o = V.agent_v8(it(copy.deepcopy(D), "What is revenue in 2018?"), m)
    assert "v8_ptr_repair" not in m.tags and o["v8"]["features"]["agree"] == pytest.approx(1 / (V.K + 1), abs=1e-3)


def test_majority_vote_and_all_samples_logged():
    a, b = {"type": "span", "args": ["$1,100.0"]}, {"type": "span", "args": ["$1,200.5"]}
    m = TagM([a] + [b] * V.K)
    o = V.agent_v8(it(copy.deepcopy(D), "What is revenue?"), m)
    assert o["v8"]["B"]["answer"] == "1200.5" and o["v8"]["A"]["answer"] == "1100"
    assert len(o["v8"]["samples"]) == V.K + 1 and o["answer"] == o["v8"]["BC"]["answer"]


def test_tie_prefers_t0_pointer():
    a, b, c = {"type": "span", "args": ["$1,100.0"]}, {"type": "span", "args": ["$1,200.5"]}, {"type": "span", "args": ["x"]}
    m = TagM([a, b, a, b] + [c] * (V.K - 3))
    o = V.agent_v8(it(copy.deepcopy(D), "What is revenue?"), m)
    assert o["v8"]["B"]["answer"] == "1100"


def _gold_item(question):
    i = it(copy.deepcopy(D), question)
    i["q"].update({"answer": ["LEAK"], "answer_type": "multi-span", "scale": "billion", "derivation": "999-1", "answer_from": "text"})
    i["doc"]["questions"] = [copy.deepcopy(i["q"])]
    return i


def _strip(i):
    j = copy.deepcopy(i); j["q"] = {"question": i["q"]["question"], "uid": i["q"]["uid"]}; j["doc"].pop("questions", None); return j


@pytest.mark.parametrize("ptr", [ARITH, {"type": "span", "args": ["x"]}, {"type": "span", "args": ["$1,200.5"], "scale_source": "(in millions)"}])
@pytest.mark.parametrize("question", ["What is the revenue in 2019?", "What is the percentage change in revenue?"])
def test_no_gold_leakage_v8(ptr, question):
    m1, m2 = TagM([ptr] * (V.K + 2)), TagM([ptr] * (V.K + 2))
    o1 = V.agent_v8(_gold_item(question), m1); o2 = V.agent_v8(_strip(_gold_item(question)), m2)
    clean = lambda o: re.sub(r'"t": [0-9.]+', '"t": 0', json.dumps(o, sort_keys=True, default=str))
    assert clean(o1) == clean(o2)
    assert m1.msgs == m2.msgs and "LEAK" not in "".join(m1.msgs) and "999-1" not in "".join(m1.msgs)
