"""V7.1 (development after the pre-registered run): structured output, extractive spans, expanded traceability check,
semantic-correctness metric. Fixtures are SYNTHETIC docs reproducing the failure shapes of test500 audit items
0a5bf43b11e9, 2238ca90aabc, 4ae88a16a8a9, 4c309d1eb940, c3ef3efb4a4e (trace_audit/TEST500_ERRORS.csv)."""
import importlib, json
import pytest
from bench import v71 as V
from bench.semantic import semantic_correct


def doc(table, paras):
    return {"table": {"table": table}, "paragraphs": [{"order": i + 1, "text": t} for i, t in enumerate(paras)]}


class FakeM:
    def __init__(self, outs):
        self.outs, self.calls, self.tags = list(outs), 0, []

    def call_json(self, msgs, tag, *a, **k):
        self.calls += 1; self.tags.append(tag)
        return self.outs.pop(0) if self.outs else {}


D_INTANG = doc([["", "September 28, 2019", "September 28, 2018"], ["Intangible assets", "1,200", "(35)"]],
               ["Intangible assets were negative at September 28, 2018 due to an impairment."])
D_CASH = doc([["(in millions)", "2019", "2018"], ["Cash paid for interest", "60.5", "100.0"]], ["Cash paid for interest fell."])
D_DEBT = doc([["", "Less than 1 year", "1-3 years"], ["Long-term debt obligations ($ in thousands)", "1,000", "51,054"]], ["Contractual obligations."])
D_GOOD = doc([["(in thousands)", "2018", "2017"], ["Goodwill impairment and restructuring charges", "9,174", "9,170"]], ["Charges."])
D_OPT = doc([["", "31 March 2019", "31 March 2018"], ["Options outstanding", "1,000", "900"]], ["Options outstanding at 31 March."])


def it(d, question, uid="x"):
    return {"id": uid, "doc": d, "q": {"question": question, "uid": uid}}


# ---------- 2) extractive spans ----------
def test_extract_exact_cell_returns_original_text():
    e = V.extract("september 28, 2018", V.sources(D_INTANG))
    assert e["found"] and e["method"] == "exact" and e["text"] == "September 28, 2018" and e["kind"] == "cell"


def test_extract_fuzzy_and_not_found_fallback():
    e = V.extract("Intangible asets were negativ", V.sources(D_INTANG))
    assert e["found"] and e["method"] == "fuzzy" and e["ratio"] >= V.FUZZY_MIN
    assert not V.extract("completely unrelated revenue sentence", V.sources(D_INTANG))["found"]
    ans, log = V.structure({"answer_type": "span", "value": "foo bar", "quote": "zzz qqq www"}, D_INTANG)
    assert ans["answer"] == "foo bar" and any(x["step"] == "extract_fallback" for x in log)


# ---------- 0a5bf43b11e9: year question answered with a full date ----------
def test_year_question_repaired_and_gate_passes():
    m = FakeM([{"answer_type": "span", "value": "September 28, 2018", "quote": "September 28, 2018", "scale": "",
                "evidence": ["| Intangible assets | 1,200 | (35) |"], "confidence": 1}])
    r = V.agent_mk71(it(D_INTANG, "In which year was intangible assets negative?"), m)
    assert r["answer"] == "2018"
    reps = r["v71"]["rounds"][0]["repairs"]
    assert reps and reps[0]["rule"] == "year_only"


def test_year_question_gate_fails_on_non_year_span():
    D = V.gate71({"answer": "September 28", "answer_type": "span", "scale": "", "evidence": ["x"]},
                 "In which year was intangible assets negative?", D_INTANG, [])
    assert any(d["check"] == "span_length" and d["verdict"] == "FAIL" for d in D)


# ---------- 2238ca90aabc: scale missing although the source is in millions ----------
def test_scale_check_flags_missing_million_and_final_scale_from_evidence():
    ans = {"answer": -39.5, "answer_type": "arithmetic", "scale": "", "expression": "60.5 - 100.0",
           "evidence": ["| Cash paid for interest | 60.5 | 100.0 |"]}
    D = V.gate71(ans, "What was the change in Cash paid for interest between 2018 and 2019?", D_CASH, [])
    sc = next(d for d in D if d["check"] == "scale_vs_evidence")
    assert sc["verdict"] == "FAIL" and "million" in sc["reason"]
    m = FakeM([{**ans, "value": -39.5, "confidence": 1}, {**ans, "value": -39.5, "scale": "million", "confidence": 1}])
    r = V.agent_mk71(it(D_CASH, "What was the change in Cash paid for interest between 2018 and 2019?"), m)
    assert r["scale"] == "million" and float(r["answer"]) == -39.5


# ---------- 4ae88a16a8a9: negative 'difference' ----------
def test_sign_check_difference_negative():
    ans = {"answer": -50054, "answer_type": "arithmetic", "scale": "thousand", "expression": "1000 - 51054",
           "evidence": ["| Long-term debt obligations ($ in thousands) | 1,000 | 51,054 |"]}
    D = V.gate71(ans, "What is the difference in long-term debt obligations between 'less than 1 year' and '1-3 years'?", D_DEBT, [])
    assert any(d["check"] == "sign" and d["verdict"] == "FAIL" for d in D)


def test_sign_check_answer_vs_expression():
    ans = {"answer": 5, "answer_type": "arithmetic", "scale": "", "expression": "1 - 6", "evidence": ["x"]}
    D = V.gate71(ans, "What was the change in X?", D_DEBT, [])
    assert next(d for d in D if d["check"] == "sign")["verdict"] == "FAIL"


# ---------- 4c309d1eb940: list instead of the sum ----------
def test_list_for_arithmetic_fails():
    ans = {"answer": ["9174", "9170"], "answer_type": "arithmetic", "scale": "thousand", "expression": "",
           "evidence": ["| Goodwill impairment and restructuring charges | 9,174 | 9,170 |"]}
    D = V.gate71(ans, "What is the total goodwill impairment and restructuring charges in 2017 and 2018?", D_GOOD, [])
    assert next(d for d in D if d["check"] == "single_number")["verdict"] == "FAIL"


# ---------- c3ef3efb4a4e: empty answer with no evidence passed the old gate ----------
def test_empty_answer_without_evidence_is_blocked():
    m = FakeM([{"answer_type": "multi-span", "value": [], "quote": [], "evidence": []}] * 2)
    r = V.agent_mk71(it(D_OPT, "In which years was the number of options outstanding at 31 March calculated?"), m)
    assert r["blocked"] is True and r["gate_passed"] is False and r["confidence_det"] == 0.0 and r["answer"] == ""
    fg = {d["check"]: d for d in r["v71"]["final_gate"]}
    assert fg["non_empty_answer"]["verdict"] == "BLOCK" and fg["has_evidence"]["verdict"] == "BLOCK"
    assert all(d["reason"] for d in r["v71"]["final_gate"])  # every decision carries its reason


def test_evidence_but_empty_answer_blocked():
    D = V.gate71({"answer": "", "answer_type": "span", "scale": "", "evidence": ["x"]}, "q?", D_OPT, [])
    assert next(d for d in D if d["check"] == "non_empty_answer")["verdict"] == "BLOCK"


# ---------- 1) structured output ----------
def test_structured_multispan_cut_from_source():
    ans, log = V.structure({"answer_type": "multi-span", "value": ["2019", "2018"], "quote": ["31 March 2019", "31 march 2018"]}, D_OPT)
    assert ans["answer"] == ["31 March 2019", "31 March 2018"] and all(x["found"] for x in log if x["step"] == "extract")


def test_invalid_answer_type_fails_gate():
    D = V.gate71({"answer": "1", "answer_type": None, "scale": "", "evidence": ["x"]}, "q?", D_OPT, [])
    assert next(d for d in D if d["check"] == "answer_type")["verdict"] == "FAIL"


# ---------- flag: V7 frozen config untouched ----------
def test_flag_off_no_v71_system(monkeypatch):
    monkeypatch.delenv("V71", raising=False)
    import bench.tatqa as TQ
    importlib.reload(TQ)
    assert "agent_mk71" not in TQ.SYSTEMS and "agent_mk" in TQ.SYSTEMS
    monkeypatch.setenv("V71", "1")
    importlib.reload(TQ)
    assert "agent_mk71" in TQ.SYSTEMS
    monkeypatch.delenv("V71")
    importlib.reload(TQ)


def test_frozen_config_does_not_mention_v71():
    from pathlib import Path
    fz = Path(__file__).resolve().parents[1] / "bench" / "freeze" / "test500_v1.json"
    assert "v71" not in fz.read_text().lower()


# ---------- 6) semantic correctness ----------
@pytest.mark.parametrize("pred,ps,gold,gs,at,exp", [
    ("-39.5", "", "-39.5", "million", "arithmetic", True),          # 2238ca90aabc: knew it, scale label missing
    ("September 28, 2018", "", "2018", "", "span", True),            # 0a5bf43b11e9: gold contained
    ("-50054", "thousand", "50054", "thousand", "arithmetic", False),  # sign never relaxed
    (["9174", "9170"], "thousand", "18344", "thousand", "arithmetic", False),
    ("", "", ["2019", "2018"], "", "multi-span", False),              # c3ef3efb4a4e
    (["2019", "2018"], "", ["2018", "2019"], "", "multi-span", True),
    ("0.12", "", "12", "percent", "arithmetic", True),
])
def test_semantic(pred, ps, gold, gs, at, exp):
    assert semantic_correct(pred, ps, gold, gs, at)[0] is exp


def test_numeric_table_span_gets_scale_and_format():
    d = doc([["(in millions)", "2019"], ["Aerospace and Defense", "$1,327.9"]], ["Segment sales."])
    o = {"answer_type": "span", "value": "1327.9", "quote": "$1,327.9", "scale": None, "evidence": ["| Aerospace and Defense | $1,327.9 |"]}
    m = FakeM([o, o])  # scale check fails -> one retry; final scale filled deterministically from the evidence unit
    r = V.agent_mk71(it(d, "What is the Aerospace and Defense value in 2019?"), m)
    assert r["answer"] == "1327.9" and r["scale"] == "million"
