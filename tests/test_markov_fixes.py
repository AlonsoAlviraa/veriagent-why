"""Regression tests for the Markov-control battery bug fixes (B1-B9, docs/BENCHMARKS.md 'Markov control battery n=100')."""
import json
import duckdb
from bench import insightbench as IB, tatqa as TQ
from bench.llmio import Meter
from bench.markov import Controller


def test_b1_quote_failure_retries_instead_of_stop():
    c = Controller()
    assert c.gate_retry(["evidence not found in context: £m 2019: 0.8"], 0, True) is True
    assert c.log[-1]["action"] == "RETRY"
    assert c.gate_retry(["evidence not found in context: x"], 1, True) is False  # round cap unchanged (2 rounds)


def test_b4_norm_ids_reads_dict_keys():
    store = {"q1": "a", "q2": "b"}
    assert IB.norm_ids([{"q2": "Fred Luddy | 41 | 27113"}], store) == ["q2"]
    assert IB.norm_ids([{"id": "q1"}], store) == ["q1"]
    assert IB.norm_ids(["q1", "[q2]", 2], store) == ["q1", "q2"]


def test_b6_repair_prompt_names_tables_and_keeps_full_error():
    p = IB.repair_prompt("CTX", ["data", "sys_user"], "Q", "SELECT * FROM incidents", "ERROR X")
    assert "THE ONLY TABLES ARE: data, sys_user" in p and "ERROR X" in p
    con = duckdb.connect()
    con.execute("CREATE TABLE data AS SELECT 1 AS a")
    err = IB.run_sql(con, "SELECT " + "a, " * 80 + "zzz_missing FROM data", IB.ERR_CHARS)
    assert err.startswith("ERROR") and len(err) > 230  # baseline cut at 200 chars
    assert len(IB.run_sql(con, "SELECT nope FROM data")) <= 200 + 40  # baseline default unchanged


def test_b7_unknown_error_class_gets_one_repair():
    c = Controller()
    assert c.sql_repair("ERROR InvalidInputException: weird", 0, None) is True
    assert c.sql_repair("ERROR InvalidInputException: weirder", 1, "ERROR InvalidInputException: weird") is False


def test_b2_b3_numeric_prompt_forbids_quoting_calculator():
    assert "never" in TQ.QUOTE_RULE.lower() or "character-for-character" in TQ.QUOTE_RULE


class _Script(Meter):
    """Offline meter returning scripted replies and recording the prompts it was sent."""
    def __init__(self, replies):
        super().__init__(50, True)
        self.replies, self.sent = list(replies), []

    def call(self, messages, tag, tier="s2", max_tokens=800, model=None):
        self.calls += 1
        self.sent.append((tag, messages))
        return self.replies.pop(0) if self.replies else "{}"


def _task():
    return {"id": "flag-x", "metadata": {"goal": "why", "role": "", "dataset_description": ""}}


def test_b5_b8_rewrite_echoes_raw_draft_and_flags_uncited_then_autocites():
    con = duckdb.connect()
    con.execute("CREATE TABLE data AS SELECT 'Fred' AS who, 41 AS n UNION ALL SELECT 'Ann', 7")
    plan = json.dumps({"steps": [{"question": "q", "sql": "SELECT who, n FROM data"}] * 5})
    draft = json.dumps({"insights": [{"text": "Fred handles 41 tickets", "evidence": []}, {"text": "Fred again 41", "evidence": []},
                                     {"text": "Ann has 7", "evidence": [{"q1": "Ann | 7"}]},
                                     {"text": "x", "evidence": ["q1"]}, {"text": "y", "evidence": ["q2"]}], "summary": "s"})
    m = _Script([plan, draft, draft, draft])
    out = IB.agent_markov(_task(), con, ["data"], m)
    writes = [msgs for tag, msgs in m.sent if tag == "write"]
    assert len(writes) >= 2  # uncited numeric claim triggered a rewrite (B8)
    echoed = writes[1][-2]["content"]
    assert "unsupported_numbers" not in echoed and "number_log" not in echoed  # raw draft echoed (B5)
    assert "cite no valid result id" in writes[1][-1]["content"]
    fred = [c for c in out["claims"] if c["text"].startswith("Fred")][0]
    assert fred["evidence"] and out["auto_cited"] >= 1  # deterministic citation repair
    ann = [c for c in out["claims"] if c["text"].startswith("Ann")][0]
    assert ann["evidence"] == ["q1"]  # dict-key citation parsed (B4)


def test_b3_quote_normaliser_commas_and_pipes():
    ctx = "TABLE\n| Total prepaid expenses and other | $2,496 | $1,947 |\nPARAGRAPHS\n[P1] Revenue was 4,351 in 2019."
    for q in ("Total prepaid expenses and other $2,496 $1,947", "4351", "| Total prepaid expenses and other | $2,496 |"):
        assert not [r for r in TQ.gate({"answer": "x", "evidence": [q]}, ctx) if r.startswith("evidence")], q
    assert TQ.gate({"answer": "x", "evidence": ["Total Revenue $3,037,000 (2019)"]}, ctx)  # invented quote still rejected
    from bench.explain import tat_metrics
    m = tat_metrics({"answer": "4351", "evidence": ["4351"], "raw": {"answer": "4351", "expression": ""}}, ctx)
    assert m["citations_valid"] == 1 and m["claims_traceable"] == 1
