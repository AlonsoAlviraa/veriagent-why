"""Regression tests for battery fixes B10-B11 and audit items #2-#6 (docs/BENCHMARKS.md 'Markov control battery n=100')."""
import json
import pytest
from bench import tatqa as TQ, tat_post as TP, llmio
from bench.llmio import Meter


def test_b10_safe_eval_wrappers_equals_unicode_and_units():
    assert TQ.safe_eval("abs(3 - 5)") == 2
    assert TQ.safe_eval("calc(1,200 + 300)") == 1500
    assert TQ.safe_eval("10 + 5 = 15") == 15
    assert TQ.safe_eval("\u221210 + 4") == -6
    assert TQ.safe_eval("$1,000 million - 200") == 800
    with pytest.raises(Exception):
        TQ.safe_eval("1, 2")  # a comma list is not a number


def test_b11_percent_in_parentheses_does_not_crash():
    TP.fmt_number("(39%)")  # crashed infer_scale before B11
    doc = {"table": {"table": [["", "2019"], ["Change", "(39%)"]]}, "paragraphs": []}
    TP.infer_scale("What was the change?", "-39", "", doc)


def _doc(head, rows, paras=()):
    return {"table": {"table": [head] + rows}, "paragraphs": [{"order": i + 1, "text": p} for i, p in enumerate(paras)]}


def test_audit2_paragraph_unit_and_unicode_minus():
    d = _doc(["", "2019", "2018"], [["Revenue", "1,200", "\u22121,100"]], ["Amounts in thousands, except per share data."])
    assert TP.infer_scale("What was Revenue in 2019?", "1200", "", d) == "thousand"
    assert TP._clean("\u22121,100") == "-1100"


def test_audit2_currency_prefixed_unit_in_header():
    d = _doc(["", "2019 S$ million", "2018 S$ million"], [["Revenue", "41.5", "40.0"]])
    assert TP.infer_scale("What was Revenue in 2019?", "41.5", "", d) == "million"


class _FakeMeter(Meter):
    def __init__(self, replies):
        super().__init__(10, True)
        self._r = list(replies)

    def call(self, messages, tag, tier="s2", max_tokens=800, model=None):
        return self._r.pop(0)


def test_audit5_call_json_retries_and_logs():
    m = _FakeMeter(["sorry, no json", '{"answer": "7"}'])
    assert m.call_json([{"role": "user", "content": "q"}], "t") == {"answer": "7"}
    assert m.parse_failures == 1 and m.parse_log[0]["retry"] == 1
    m = _FakeMeter(["x", "y"])
    assert m.call_json([{"role": "user", "content": "q"}], "t") == {}
    assert m.parse_failures == 2 and m.parse_log[-1]["retry"] == "gave_up"
    assert "parse_failures" in m.snapshot()


def test_audit6_judge_none_excluded_and_counted():
    from bench import report
    def rec(i, j):
        return {"bench": "insightbench", "system": "s", "id": f"flag-{i}", "error": None, "confidence": 0.5, "confidence_det": 0.5,
                "seconds": 1, "meter": {"calls": 1, "prompt_tokens": 1, "completion_tokens": 1},
                "scores": {"insight_rouge1": 0.3, "summary_rouge1": 0.3, "summary_judge": j}, "output": {}}
    d = report.summarise([rec(1, 0.8), rec(2, None), rec(3, 0.2)])[0]
    assert d["judge_none"] == 1
    assert "1/2" in str(d["judge>=0.6 (secondary)"]) or "50" in str(d["judge>=0.6 (secondary)"])


def test_audit4_judge_model_is_super_by_default():
    assert llmio.JUDGE_MODEL == "nvidia/nemotron-3-super-120b-a12b"


def test_insightbench_split_fixed_and_disjoint():
    s = json.load(open("bench/splits/insightbench_split.json"))
    assert len(s["tune"]) == 30 and len(s["eval"]) == 70 and not set(s["tune"]) & set(s["eval"])


def test_no_gold_paraphrase_in_prompt_example():
    from bench import insightbench as IB
    import inspect
    assert "north depot" in inspect.getsource(IB)


def _vr_meter(scores):
    class M:
        def __init__(s): s.calls = []
        def call_json(s, msgs, tag, tier="s2", mt=800, model=None):
            s.calls.append(model)
            v = scores.pop(0)
            return {"score": v, "feedback": "fb"} if v is not None else {}
    return M()


def test_verify_retry_stops_on_threshold_patience_and_cap():
    from bench import verify as V
    gen = lambda fb: {"a": 1, "fb": fb}
    chk = lambda r: ({"answer": 1, "claims": [], "evidence": []}, 100.0, [])
    m = _vr_meter([80])
    r = V.loop(m, "q", gen, chk)  # 0.5*100 + 0.5*80 = 90 >= 50 -> 1 attempt
    assert r["vr_n_attempts"] == 1 and r["confidence"] == 0.9 and m.calls == [V.VERIFIER_MODEL]
    chk0 = lambda r: ({}, 0.0, ["no evidence cited"])
    r = V.loop(_vr_meter([20, 10, 10]), "q", gen, chk0)  # no improvement twice -> stop at 3
    assert r["vr_n_attempts"] == 3 and r["vr_best_attempt"] == 1 and r["vr_attempts"][1]["delta"] == -5.0
    r = V.loop(_vr_meter([10, 20, 30, 40, 48]), "q", gen, chk0)
    assert r["vr_n_attempts"] == V.MAX_ATTEMPTS and r["vr_score"] == 24.0
    r = V.loop(_vr_meter([None]), "q", gen, chk)  # verifier None -> det only, flagged
    assert r["vr_attempts"][0]["verifier_none"] and r["vr_score"] == 100.0


def test_verifier_never_sees_gold():
    from bench import verify as V
    seen = []
    class M:
        def call_json(s, msgs, *a, **k):
            seen.append(json.dumps(msgs)); return {"score": 90}
    V.llm_verify(M(), "What was X?", {"answer": "5", "evidence": ["X | 5"]})
    assert "gold" not in seen[0].lower() and "What was X?" in seen[0]
