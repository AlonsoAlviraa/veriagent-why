"""v2 (post-audit) benchmark fixes: scale/format post-step, flatten, gate with derived numbers,
evidence-id normalisation, explainability metrics, calibration, bootstrap, reporting."""
import json
from bench import explain as EX, insightbench as IB, report, run, tat_post as P, tatqa as TQ
from bench.common import bootstrap_mean, brier, conf01, derived_pool, ece, gate_claim


def _doc(head="(in thousands)", paras=None):
    return {"table": {"table": [["", head, ""], ["", "2019", "2018"], ["Revenue", "$1,200", "$1,000"]]},
            "paragraphs": paras or [{"order": 1, "text": "Revenue grew."}], "questions": []}


def test_format_number():
    assert P.fmt_number("$1,327.90") == "1327.9" and P.fmt_number("15.987") == "15.99"
    assert P.fmt_number("(12.5)") == "-12.5" and P.fmt_number("20%") == "20" and P.fmt_number("abc") == "abc"


def test_scale_from_table_header_and_percent_and_count():
    d = _doc()
    assert P.infer_scale("What was revenue in 2019?", "1200", "", d) == "thousand"
    assert P.infer_scale("What is the change in revenue?", "200", "1200-1000", d) == "thousand"
    assert P.infer_scale("What is the percentage change in revenue?", "20", "(1200-1000)/1000*100", d) == "percent"
    assert P.infer_scale("How many years are shown?", "2", "", d) == ""
    assert P.infer_scale("In which years was revenue above 1,100?", ["2019"], "", d) == ""
    assert P.infer_scale("What was revenue?", "Revenue grew", "", d) == ""
    assert P.infer_scale("What was revenue in 2019?", "1200", "", _doc(head="Year")) == ""  # no unit stated -> ""
    assert P.infer_scale("What was revenue?", "1200", "", _doc(head="USD ‘000")) == "thousand"


def test_scale_from_paragraph_number_unit():
    d = _doc(head="Year", paras=[{"order": 1, "text": "Backlog was $3.4 million at year end."}])
    assert P.infer_scale("What was the backlog?", "3.4", "", d) == "million"


def test_postprocess_never_reads_gold():
    d = _doc()
    q = {"question": "What was revenue in 2019?", "answer": "SECRET", "scale": "billion"}
    d["questions"] = [q]
    out = P.postprocess({"answer": "$1,200", "scale": "", "expression": ""}, q["question"], {"table": d["table"], "paragraphs": d["paragraphs"]})
    assert out == {"answer": "1200", "scale": "thousand", "expression": ""}


def test_flatten_list_of_dicts_fixes_sorted_typeerror():
    assert P.flatten([{"2019": "a"}, {"2018": "b"}]) == ["a", "b"]
    assert P.flatten({"x": "1"}) == ["1"] and P.flatten(3) == "3" and P.flatten(None) == ""


def test_tatqa_pred_keeps_raw_and_scores_list_of_dicts():
    from pathlib import Path
    it = {"id": "x", "doc": _doc(), "q": {"question": "What are the revenues in 2019 and 2018 respectively?", "answer": ["1,200", "1,000"],
                                         "scale": "thousand", "answer_type": "multi-span", "answer_from": "table"}}
    p = TQ._pred({"answer": [{"2019": "$1,200"}, {"2018": "$1,000"}], "scale": "", "evidence": ["$1,200"], "confidence": 80}, it)
    assert p["answer"] == ["1200", "1000"] and p["scale"] == "thousand" and p["raw"]["scale"] == "" and p["confidence"] == 0.8
    d = Path(__file__).resolve().parents[1] / "data" / "bench" / "tatqa"
    if (d / "tatqa_metric.py").exists():
        em, _ = TQ.item_em(d, it, p)
        assert em == 1.0


def test_prompt_has_tatqa_rules():
    assert "SHORTEST exact span" in TQ.ANS and "2 decimal places" in TQ.ANS and "percent" in TQ.ANS


def test_gate_allows_derived_and_logs_reason():
    src = ["category | n\nHardware | 335\nSoftware | 165"]
    bad, log = gate_claim("Hardware (335) exceeds Software by 170 (2.03x), total 500", src)
    assert bad == [] and {l["status"] for l in log} == {"direct", "derived"}
    bad, log = gate_claim("Hardware has 999 incidents", src)
    assert bad == [999.0] and log[-1]["reason"]
    assert 170 in derived_pool([335, 165])


def test_norm_ids_dicts_and_variants():
    store = {"q1": "a", "q2": "b", "data#3": "c", "2": "x"}
    assert IB.norm_ids([{"id": "q1"}, "[q2]", "data#3", 1], {k: v for k, v in store.items() if k != "2"}) == ["q1", "q2", "data#3"]
    assert IB.norm_ids(["observation 2"], {"2": "x"}) == ["2"]
    assert IB.norm_ids(None, store) == [] and IB.norm_ids("q1", store) == ["q1"]


def test_insight_explain_metrics():
    out = {"evidence_store": {"q1": "c | n\nA | 335\nB | 165", "q2": "x | 7"},
           "claims": [{"text": "A has 335 incidents, 170 more than B", "evidence": ["q1"]},
                      {"text": "A has 999 incidents", "evidence": ["q1", "q9"]},
                      {"text": "A dominates", "evidence": []}],
           "summary": "A leads with 335."}
    m = EX.insight_metrics(out)
    assert m == {"claims": 3, "citations": 3, "citations_valid": 1, "claims_traceable": 1, "numbers": 4, "numbers_unsupported": 1}


def test_tat_explain_metrics():
    ctx = "| Revenue | $1,200 | $1,000 |"
    m = EX.tat_metrics({"raw": {"answer": "20", "expression": "(1200-1000)/1000*100"}, "evidence": ["$1,200", "$1,000", "made up"]}, ctx)
    assert m["citations"] == 3 and m["citations_valid"] == 2 and m["claims_traceable"] == 1
    assert EX.tat_metrics({"raw": {"answer": "4321"}, "evidence": []}, ctx)["claims_traceable"] == 0


def test_calibration_and_bootstrap():
    assert brier([1.0, 0.0], [1, 0]) == 0 and brier([1.0], [0]) == 1
    assert ece([0.9] * 10, [1] * 9 + [0]) == 0.0 and ece([0.9] * 10, [0] * 10) == 0.9
    lo, hi = bootstrap_mean([0.0, 1.0] * 20)
    assert lo < 0.5 < hi and bootstrap_mean([]) == (0.0, 0.0)
    assert conf01("85") == 0.85 and conf01(0.3) == 0.3 and conf01(None) is None and conf01("high") is None


def test_report_v2_fields_and_empty_gold(tmp_path):
    out = tmp_path / "r.jsonl"
    assert run.main(["--bench", "insightbench", "--offline", "--fixtures", "--out", str(out), "--max-calls", "80"]) == 0
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert all("explain" in r and "evidence_store" in r["output"] for r in rows)
    assert all(r["explain"].get("faithfulness") is not None for r in rows)
    r0 = dict(rows[0]); r0["id"] = "flag-36"; r0["scores"] = {**r0["scores"], "excluded": "empty ground-truth insights in the dataset"}
    s = report.summarise(rows + [r0])
    a = [d for d in s if d["system"] == "agent"][0]
    assert a["excluded"] == ["flag-36"] and a["n_scored"] == 1 and "claim_traceability" in a and "sql_error_rate_first_try" in a


def test_tatqa_report_v2_fields(tmp_path):
    out = tmp_path / "t.jsonl"
    assert run.main(["--bench", "tatqa", "--offline", "--fixtures", "--out", str(out), "--max-calls", "50"]) == 0
    s = report.summarise(report.load(out))
    assert all("by_answer_type" in d and "citation_precision" in d for d in s)


def test_agent_sql_retry_feeds_error(monkeypatch):
    seen = []
    from bench import llmio
    orig = llmio.fake
    def fk(messages, tag):
        if tag == "plan":
            return json.dumps({"steps": [{"question": "q", "sql": "SELECT nope FROM data"}]})
        if tag == "sqlfix":
            seen.append(messages[-1]["content"])
        return orig(messages, tag)
    monkeypatch.setattr(llmio, "fake", fk)
    t = run.select("insightbench", True, 1, None)[0]
    con, tables = IB.connect(t, t["_root"])
    res = IB.agent(t, con, tables, llmio.Meter(40, True))
    assert seen and "ERROR" in seen[0] and res["sql_errors_first_try"] >= 1 and res["sql_errors"] == 0
    assert "dropped_claims" in res
