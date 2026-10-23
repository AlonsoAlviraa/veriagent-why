"""InsightBench adapter: task JSON + CSV(s) -> DuckDB tables -> systems -> InsightBench output
({"insights": [str], "summary": str}) -> official-style scoring.

Systems, all on the SAME model through bench.llmio:
- agent: VeriAgent Why stages (Planner -> SQL retrieval -> Evidence Evaluator requery loop (max 3)
  -> Writer -> deterministic Claim Gate (max 2 rewrite rounds, then unsupported insights dropped)).
- rag:   plain RAG. Rows serialised as text, BM25 vs goal, top rows up to a token budget, one call.
- react: simple ReAct text-to-SQL agent (up to 6 SQL actions, then one final answer call). No gate.
"""
from __future__ import annotations
import json
from pathlib import Path
import duckdb
from app.bm25 import bm25
from .common import gate_text, safe_sql
from .llmio import Meter, parse_json

MAX_ROWS = 40
ROUNDS = 3
GATE_ROUNDS = 2


def load_task(path: Path, root: Path) -> dict:
    t = json.loads(Path(path).read_text())
    t["id"] = Path(path).stem
    return t


def connect(task: dict, root: Path):
    con = duckdb.connect()
    names = {}
    for key, name in (("dataset_csv_path", "data"), ("user_dataset_csv_path", "sys_user")):
        if task.get(key):
            p = str((root / task[key]).resolve()).replace("'", "''")
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_csv_auto('{p}', sample_size=-1)")
            names[name] = p
    return con, list(names)


def schema(con, tables: list[str]) -> str:
    out = []
    for t in tables:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        out.append(f"TABLE {t} ({n} rows)")
        for c, ty, *_ in con.execute(f"DESCRIBE {t}").fetchall():
            ex = [str(r[0])[:40] for r in con.execute(f'SELECT DISTINCT "{c}" FROM {t} WHERE "{c}" IS NOT NULL LIMIT 3').fetchall()]
            out.append(f"- {c} {ty} e.g. {ex}")
    return "\n".join(out)


def run_sql(con, sql: str) -> str:
    try:
        cur = con.execute(safe_sql(sql))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS)
        return " | ".join(cols) + "\n" + "\n".join(" | ".join(str(v)[:60] for v in r) for r in rows)
    except Exception as e:
        return f"ERROR {type(e).__name__}: {str(e)[:200]}"


def _context(task: dict, sch: str) -> str:
    m = task["metadata"]
    return f"GOAL: {m['goal']}\nROLE: {m.get('role','')}\nDATASET: {m.get('dataset_description','')[:1200]}\nSCHEMA:\n{sch}"


OUT_SPEC = ('Reply with JSON only (at most 6 insights, each under 40 words): {"insights": [{"text": one specific data-backed insight (descriptive, diagnostic '
            '- why it happened -, predictive or prescriptive), "evidence": [result ids]}], "summary": a short paragraph}. '
            "Every number you write must come from the results.")


def agent(task, con, tables, m: Meter) -> dict:
    sch = schema(con, tables)
    ctx = _context(task, sch)
    plan = parse_json(m.call([{"role": "system", "content": "You are the Planner of a root-cause analytics agent. Decompose the goal into analysis questions, each answered by one DuckDB SQL query over the given tables. Include diagnostic (why) questions. Reply with JSON only: {\"steps\": [{\"question\": str, \"sql\": str}]} (max 6)."},
                              {"role": "user", "content": ctx}], "plan", "s2", 1500)) or {}
    steps, results = list(plan.get("steps") or [])[:6], {}
    for rnd in range(ROUNDS):
        for s in steps:
            qid = f"q{len(results) + 1}"
            results[qid] = {"question": s.get("question", ""), "sql": s.get("sql", ""), "result": run_sql(con, s.get("sql", ""))}
        if rnd == ROUNDS - 1:
            break
        ev = parse_json(m.call([{"role": "system", "content": "You are the Evidence Evaluator. Given the goal and the query results, decide whether the evidence is sufficient to explain WHY, or propose follow-up queries (drill-downs, comparisons, fixes for failed SQL). Reply with JSON only: {\"sufficient\": bool, \"new_steps\": [{\"question\": str, \"sql\": str}]} (max 4)."},
                                {"role": "user", "content": ctx + "\nRESULTS\n" + _fmt(results)}], "evaluate", "s1", 1200)) or {}
        steps = list(ev.get("new_steps") or [])[:4]
        if ev.get("sufficient") or not steps:
            break
    msgs = [{"role": "system", "content": "You are the Writer of a root-cause analytics agent. " + OUT_SPEC},
            {"role": "user", "content": ctx + "\nRESULTS\n" + _fmt(results)}]
    gate_log = []
    prev = None
    for g in range(GATE_ROUNDS + 1):
        out = parse_json(m.call(msgs, "write", "s2", 2500)) or {}
        ins = [i for i in (out.get("insights") or []) if isinstance(i, dict) and i.get("text")]
        if not ins and prev:  # unparseable/empty rewrite: keep previous draft; the gate still drops its unsupported insights
            out, ins = prev
            gate_log.append({"round": g, "insights": 0, "note": "empty rewrite, kept previous draft"})
            break
        bad = []
        for i in ins:
            src = [results[e]["result"] for e in (i.get("evidence") or []) if e in results] or [r["result"] for r in results.values()]
            un = gate_text(i["text"], src)
            i["unsupported_numbers"] = un
            if un:
                bad.append(i)
        sum_un = gate_text(out.get("summary", ""), [r["result"] for r in results.values()])
        gate_log.append({"round": g, "insights": len(ins), "failed": len(bad), "summary_unsupported": sum_un})
        if (not bad and not sum_un) or g == GATE_ROUNDS:
            break
        prev = (out, ins)
        msgs = msgs + [{"role": "assistant", "content": json.dumps(out)[:4000]},
                       {"role": "user", "content": "Claim gate rejected these numbers as not present in the cited results: "
                        + json.dumps([{"text": i["text"], "unsupported": i["unsupported_numbers"]} for i in bad] + ([{"summary": sum_un}] if sum_un else []))
                        + ". Rewrite. " + OUT_SPEC}]
    kept = [i for i in ins if not i["unsupported_numbers"]]
    return {"insights": [i["text"] for i in kept], "summary": out.get("summary", ""),
            "dropped_by_gate": len(ins) - len(kept), "gate": gate_log, "queries": len(results),
            "sql_errors": sum(r["result"].startswith("ERROR") for r in results.values())}


def _fmt(results: dict) -> str:
    return "\n".join(f"[{k}] {v['question']}\nSQL: {v['sql']}\n{v['result'][:1500]}" for k, v in results.items())


def rag(task, con, tables, m: Meter, token_budget: int = 3000) -> dict:
    docs = []
    for t in tables:
        cur = con.execute(f"SELECT * FROM {t}")
        cols = [d[0] for d in cur.description]
        for i, r in enumerate(cur.fetchall()):
            docs.append(f"[{t}#{i}] " + "; ".join(f"{c}={str(v)[:80]}" for c, v in zip(cols, r)))
    sc = bm25(docs, task["metadata"]["goal"])
    ctx, used = [], 0
    for i in sorted(range(len(docs)), key=lambda i: -sc[i]):
        n = len(docs[i]) // 4 + 1  # ~4 chars per model token
        if used + n > token_budget:
            break
        ctx.append(docs[i]); used += n
    out = parse_json(m.call([{"role": "system", "content": "Answer the analytics goal from the retrieved rows only. " + OUT_SPEC.replace("result ids", "row ids")},
                             {"role": "user", "content": f"GOAL: {task['metadata']['goal']}\nRESULTS (retrieved rows)\n" + "\n".join(ctx)}], "rag", "s2", 2500)) or {}
    ins = [i["text"] if isinstance(i, dict) else str(i) for i in (out.get("insights") or [])]
    return {"insights": [i for i in ins if i], "summary": out.get("summary", ""), "context_tokens": used}


def react(task, con, tables, m: Meter, max_steps: int = 6) -> dict:
    ctx = _context(task, schema(con, tables))
    hist = ""
    for s in range(max_steps):
        a = parse_json(m.call([{"role": "system", "content": "You are a ReAct data analyst with one tool: DuckDB SQL. Each turn reply with JSON only: {\"thought\": str, \"action\": \"sql\", \"sql\": str} or {\"action\": \"final\"} when you have enough."},
                               {"role": "user", "content": ctx + hist}], "react", "s2", 800)) or {}
        if a.get("action") != "sql" or not a.get("sql"):
            break
        hist += f"\nACTION {s + 1}: {a['sql']}\nOBSERVATION {s + 1}:\n{run_sql(con, a['sql'])[:1500]}"
    out = parse_json(m.call([{"role": "system", "content": "Write the final answer. " + OUT_SPEC.replace("result ids", "observation numbers")},
                             {"role": "user", "content": ctx + "\nRESULTS" + hist}], "react_final", "s2", 2500)) or {}
    ins = [i["text"] if isinstance(i, dict) else str(i) for i in (out.get("insights") or [])]
    return {"insights": [i for i in ins if i], "summary": out.get("summary", ""), "steps": hist.count("ACTION ")}


SYSTEMS = {"agent": agent, "rag": rag, "react": react}


# ------------------------------------------------------------------ scoring
_RS = [None]


def rouge1(pred: str, gt: str) -> float:
    """ROUGE-1 F as computed by HF `evaluate`'s rouge metric defaults (rouge_score, no stemmer),
    which is what insightbench.utils.eval_utils.compute_rouge_score calls."""
    if _RS[0] is None:
        from rouge_score import rouge_scorer
        _RS[0] = rouge_scorer.RougeScorer(["rouge1"], use_stemmer=False)
    return _RS[0].score(gt, pred)["rouge1"].fmeasure


def insight_rouge(pred: list[str], gt: list[str]) -> float:
    """insightbench.metrics.compute_rouge: for each GT insight take the best-matching prediction, average."""
    if not gt:
        return 0.0
    if not pred:
        return 0.0
    return sum(max(rouge1(p, g) for p in pred) for g in gt) / len(gt)


G_EVAL_SYSTEM = "You are a high school teacher evaluating student responses to a question. You are tasked with grading the response based on how well it answers the question. You are to provide a numerical rating for how well the response answers the question based on the ground truth answer."
G_EVAL_TEMPLATE = """
Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
Provided Answer:
{answer}

Ground Truth Answer:
{gt_answer}

Follow these instructions when writing your response:
* On a scale of 1-10, provide a numerical rating for how close the provided answer is to the ground truth answer, with 10 denoting that the provided answer is the same as ground truth answer.
* Your response should contain only the numerical rating. DONOT include anything else like the provided answer, the ground truth answer, or an explanation of your rating scale in your response.
* Wrap your numerical rating inside <rating></rating> tags.
* Check very carefully before answering.
* Follow the output format as shown in the example below:
Example response:
<rating>7</rating>

### Response:

"""  # verbatim from insightbench/prompts (G_EVAL_BASIC_*), pinned commit


def judge(m: Meter, answer: str, gt: str) -> float | None:
    """Official G-Eval basic prompt, judged by Nemotron. Deviation: the free endpoint gives no
    logprobs, so we parse the integer rating (paper weights by token probabilities). Score/10."""
    import re
    r = m.call([{"role": "system", "content": G_EVAL_SYSTEM}, {"role": "user", "content": G_EVAL_TEMPLATE.format(answer=answer, gt_answer=gt)}], "judge", "s2", 50)
    x = re.findall(r"<rating>\s*(\d+)\s*</rating>", r or "") or re.findall(r"\b(10|[1-9])\b", r or "")
    return int(x[0]) / 10 if x else None


def score(task: dict, out: dict, m: Meter | None, judge_insights: bool = False) -> dict:
    gt_ins, gt_sum = task.get("insights") or [], task.get("summary") or ""
    pred_sum = out.get("summary") or " ".join(out.get("insights") or [])
    s = {"insight_rouge1": round(insight_rouge(out.get("insights") or [], gt_ins), 4),
         "summary_rouge1": round(rouge1(pred_sum, gt_sum), 4) if pred_sum and gt_sum else 0.0,
         "n_pred_insights": len(out.get("insights") or []), "n_gt_insights": len(gt_ins)}
    if m is not None:
        s["summary_judge"] = judge(m, pred_sum, gt_sum) if pred_sum else 0.0
        if judge_insights and out.get("insights"):  # o2m: |gt| x |pred| calls, opt-in only
            s["insight_judge"] = round(sum(max((judge(m, p, g) or 0) for p in out["insights"]) for g in gt_ins) / max(1, len(gt_ins)), 4)
    return s
