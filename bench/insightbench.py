"""InsightBench adapter: task JSON + CSV(s) -> DuckDB tables -> systems -> InsightBench output
({"insights": [str], "summary": str}) -> official-style scoring.

Systems, all on the SAME model through bench.llmio:
- agent: VeriAgent Why stages (Planner -> SQL retrieval -> Evidence Evaluator requery loop (max 3)
  -> Writer -> deterministic Traceability Check (max 2 rewrite rounds, then unsupported insights dropped)).
- rag:   plain RAG. Rows serialised as text, BM25 vs goal, top rows up to a token budget, one call.
- react: simple ReAct text-to-SQL agent (up to 6 SQL actions, then one final answer call). No gate.
"""
from __future__ import annotations
import json
from pathlib import Path
import duckdb
from app.bm25 import bm25
from .common import gate_claim, gate_text, nums, safe_sql, conf01
from .fixes import is_empty_result, usable, check_comparatives, sql_key
from .llmio import JUDGE_MODEL, Meter, parse_json

MAX_ROWS = 100  # v2: larger result window (v1: 40)
RESULT_CHARS = 4000  # v2 (v1: 1500)
SQL_RETRIES = 1
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


def run_sql(con, sql: str, err_chars: int = 200) -> str:
    try:
        cur = con.execute(safe_sql(sql))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS)
        return " | ".join(cols) + "\n" + "\n".join(" | ".join(str(v)[:60] for v in r) for r in rows)
    except Exception as e:
        return f"ERROR {type(e).__name__}: {str(e)[:err_chars]}"


def _context(task: dict, sch: str) -> str:
    m = task["metadata"]
    return f"GOAL: {m['goal']}\nROLE: {m.get('role','')}\nDATASET: {m.get('dataset_description','')[:1200]}\nSCHEMA:\n{sch}"


OUT_SPEC = ('Reply with JSON only (up to 10 insights): {"insights": [{"text": one or two plain-prose sentences stating a finding the way an '
            'analyst notebook would (e.g. "Orders shipped from the north depot arrive late far more often than the others, at 120 of 400"), descriptive, diagnostic '
            '- why it happened -, predictive or prescriptive, "evidence": [result ids]}], "summary": a paragraph that states the main trend and its cause '
            'in plain prose, "confidence": your probability 0-1 that the main finding is correct}. '
            "Every number you write must come from, or be computed from, the cited results.")


def agent(task, con, tables, m: Meter, vr: bool = False) -> dict:
    sch = schema(con, tables)
    ctx = _context(task, sch)
    plan = m.call_json([{"role": "system", "content": "You are the Planner of a root-cause analytics agent. Decompose the goal into analysis questions, each answered by one DuckDB SQL query over the given tables. Include diagnostic (why) questions. Reply with JSON only: {\"steps\": [{\"question\": str, \"sql\": str}]} (max 6)."},
                              {"role": "user", "content": ctx}], "plan", "s2", 1500)
    steps, results = list(plan.get("steps") or [])[:6], {}
    for rnd in range(ROUNDS):
        for s in steps:
            qid = f"q{len(results) + 1}"
            sql = str(s.get("sql", "") or "")
            res, first_err = run_sql(con, sql), None
            for _ in range(SQL_RETRIES):
                if not res.startswith("ERROR"):
                    break
                first_err = res
                fx = m.call_json([{"role": "system", "content": "Fix this DuckDB SQL query. Reply with JSON only: {\"sql\": str}."},
                                        {"role": "user", "content": ctx + f"\nQUESTION: {s.get('question','')}\nSQL: {sql}\n{res}"}], "sqlfix", "s1", 600)
                if fx.get("sql"):
                    sql = str(fx["sql"])
                    res = run_sql(con, sql)
            results[qid] = {"question": s.get("question", ""), "sql": sql, "result": res, "first_error": first_err}
        if rnd == ROUNDS - 1:
            break
        ev = m.call_json([{"role": "system", "content": "You are the Evidence Evaluator. Given the goal and the query results, decide whether the evidence is sufficient to explain WHY, or propose follow-up queries (drill-downs, comparisons, fixes for failed SQL). Reply with JSON only: {\"sufficient\": bool, \"new_steps\": [{\"question\": str, \"sql\": str}]} (max 4)."},
                                {"role": "user", "content": ctx + "\nRESULTS\n" + _fmt(results)}], "evaluate", "s1", 1200)
        steps = list(ev.get("new_steps") or [])[:4]
        if ev.get("sufficient") or not steps:
            break
    def write(fb=None, prev_out=None):
        extra = [{"role": "assistant", "content": json.dumps(prev_out)[:4000]}, {"role": "user", "content": fb + " " + OUT_SPEC}] if fb else []
        msgs = [{"role": "system", "content": "You are the Writer of a root-cause analytics agent. " + OUT_SPEC},
                {"role": "user", "content": ctx + "\nRESULTS\n" + _fmt(results)}] + extra
        gate_log = []
        prev = None
        for g in range(GATE_ROUNDS + 1):
            out = m.call_json(msgs, "write", "s2", 3500)
            ins = [i for i in (out.get("insights") or []) if isinstance(i, dict) and i.get("text")][:10]
            if not ins and prev:  # unparseable/empty rewrite: keep previous draft; the gate still drops its unsupported insights
                out, ins = prev
                gate_log.append({"round": g, "insights": 0, "note": "empty rewrite, kept previous draft"})
                break
            bad = []
            for i in ins:
                i["evidence"] = norm_ids(i.get("evidence"), results)
                src = [results[e]["result"] for e in i["evidence"]] or [r["result"] for r in results.values()]
                un, nlog = gate_claim(i["text"], src)
                i["unsupported_numbers"], i["number_log"] = un, nlog
                if un:
                    bad.append(i)
            sum_un, _ = gate_claim(out.get("summary", ""), [r["result"] for r in results.values()])
            gate_log.append({"round": g, "insights": len(ins), "failed": len(bad), "summary_unsupported": sum_un, "drafts": [i["text"] for i in ins]})
            if (not bad and not sum_un) or g == GATE_ROUNDS:
                break
            prev = (out, ins)
            msgs = msgs + [{"role": "assistant", "content": json.dumps(out)[:4000]},
                           {"role": "user", "content": "Traceability check rejected these numbers as not present in the cited results: "
                            + json.dumps([{"text": i["text"], "unsupported": i["unsupported_numbers"]} for i in bad] + ([{"summary": sum_un}] if sum_un else []))
                            + ". Rewrite. " + OUT_SPEC}]
        kept = [i for i in ins if not i["unsupported_numbers"]]
        dropped = [{"text": i["text"], "evidence": i["evidence"], "unsupported": i["unsupported_numbers"],
                    "reason": "numbers not in cited results nor recomputable from them"} for i in ins if i["unsupported_numbers"]]
        return {"_raw": out, "insights": [i["text"] for i in kept], "claims": [{"text": i["text"], "evidence": i["evidence"]} for i in kept],
                "summary": out.get("summary", ""), "confidence": conf01(out.get("confidence")),
                "confidence_det": det_confidence(results, kept, dropped),
                "dropped_by_gate": len(dropped), "dropped_claims": dropped, "gate": gate_log, "queries": len(results),
                "sql_errors": sum(r["result"].startswith("ERROR") for r in results.values()),
                "sql_errors_first_try": sum(1 for r in results.values() if r.get("first_error")),
                "evidence_store": {k: v["result"][:RESULT_CHARS] for k, v in results.items()},
                "queries_log": {k: {"question": v["question"], "sql": v["sql"], "first_error": v["first_error"]} for k, v in results.items()}}

    if not vr:
        r = write()
        r.pop("_raw")
        return r
    from . import verify as V
    st = {"last": None}

    def generate(fb):
        r = write(fb, st["last"]["_raw"] if (fb and st["last"]) else None)
        st["last"] = r
        return r

    def check(r):
        store = r["evidence_store"]
        notes = [f"dropped by gate (numbers not in cited results): {d['text'][:80]}" for d in r["dropped_claims"]]
        notes += [f"claim cites no existing query result: {c['text'][:80]}" for c in r["claims"] if not [e for e in c["evidence"] if e in store]]
        notes += ["no insights"] if not r["claims"] else []
        n = len(r["claims"]) + len(r["dropped_claims"]) + 1
        ev = sorted({e for c in r["claims"] for e in c["evidence"] if e in store})
        packet = {"answer": r["summary"], "claims": r["claims"],
                  "evidence": [{"id": e, "query": results.get(e, {}).get("sql", ""), "result": store[e][:600]} for e in ev][:12]}
        return packet, 100.0 * max(0.0, 1 - len(notes) / n), notes

    out = V.loop(m, task["metadata"]["goal"], generate, check)
    out.pop("_raw", None)
    out["confidence_det"] = out["confidence"]
    out["conf_formula"], out["conf_inputs"] = "vr_score", {"vr_score": out["vr_score"]}
    return out


def norm_ids(ev, store: dict) -> list[str]:
    """Evidence ids may come back as str, int, dict ({"id": "q1"}) or "[q1]" -> keys of `store` (fixes flag-14 TypeError)."""
    if ev is None:
        return []
    if not isinstance(ev, list):
        ev = [ev]
    out = []
    for e in ev:
        # dict citations: {"id": "q1"} (id in value) or {"q2": "<quoted row>"} (id in KEY; bug B4: keys were ignored)
        vals = (list(e.keys()) + list(e.values())) if isinstance(e, dict) else [e]
        for v in vals:
            k = str(v).strip().strip("[]").strip()
            import re as _re
            dg = _re.findall(r"\d+", k)
            for cand in (k, f"q{k}", k.lower(), *( [dg[-1], f"q{dg[-1]}"] if dg and "#" not in k else [])):
                if cand in store and cand not in out:
                    out.append(cand)
                    break
    return out


def det_confidence(results: dict, kept: list, dropped: list) -> float:
    """Deterministic confidence (declared): share of SQL results that are USABLE (ran and returned >=1 non-null row;
    trace-fix 2/4: empty results used to count as successes) x share of claims surviving the gate, capped."""
    return ib_det(len(results), sum(not usable(r["result"]) for r in results.values()), len(kept), len(dropped))


def ib_det(n_q: int, n_unusable: int, n_kept: int, n_dropped: int) -> float:
    from .confidence import ib_det as f
    return f(n_q, n_unusable, n_kept, n_dropped)


def gate_ib_claim(claim: dict, view: dict) -> tuple[list, list, list]:
    """InsightBench traceability check (trace-fixes 2+3). Sources = the cited results that are usable; if the claim cites only
    empty/failed results, its numbers have no source (unsupported); with no citation at all the usable results are the
    pool (as before). Comparatives/superlatives are checked against the cited tables (deterministic argmax/argmin)."""
    ev = [e for e in claim.get("evidence") or [] if e in view]
    src = [view[e] for e in ev if usable(view[e])]
    if not ev:
        src = [v for v in view.values() if usable(v)]
    un, nlog = gate_claim(claim["text"], src)
    contra = check_comparatives(claim["text"], [view[e] for e in ev if usable(view[e])]) if ev else []
    return un, nlog, contra


def _fmt(results: dict) -> str:
    """trace-fix 2: empty results are labelled so the Writer never cites numbers from them."""
    return "\n".join(f"[{k}] {v['question']}\nSQL: {v['sql']}\n{v['result'][:RESULT_CHARS]}"
                     + ("\n(0 rows: NO EVIDENCE - do not cite this id or state numbers from it)" if is_empty_result(v["result"]) else "") for k, v in results.items())


def rag(task, con, tables, m: Meter, token_budget: int = 6000) -> dict:  # v2: 6000 (v1: 3000)
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
    out = m.call_json([{"role": "system", "content": "Answer the analytics goal from the retrieved rows only. " + OUT_SPEC.replace("result ids", "row ids")},
                             {"role": "user", "content": f"GOAL: {task['metadata']['goal']}\nRESULTS (retrieved rows)\n" + "\n".join(ctx)}], "rag", "s2", 3500)
    store = {d.split("]", 1)[0].lstrip("["): d for d in ctx}
    claims = _claims(out, store)
    return {"insights": [c["text"] for c in claims], "claims": claims, "summary": out.get("summary", ""),
            "confidence": conf01(out.get("confidence")), "context_tokens": used, "evidence_store": store}


def _claims(out: dict, store: dict) -> list[dict]:
    res = []
    for i in (out.get("insights") or [])[:10]:
        if isinstance(i, dict) and i.get("text"):
            res.append({"text": str(i["text"]), "evidence": norm_ids(i.get("evidence"), store)})
        elif isinstance(i, str) and i:
            res.append({"text": i, "evidence": []})
    return res


def react(task, con, tables, m: Meter, max_steps: int = 6) -> dict:
    ctx = _context(task, schema(con, tables))
    hist, store, errs = "", {}, 0
    for s in range(max_steps):
        a = m.call_json([{"role": "system", "content": "You are a ReAct data analyst with one tool: DuckDB SQL. Each turn reply with JSON only: {\"thought\": str, \"action\": \"sql\", \"sql\": str} or {\"action\": \"final\"} when you have enough."},
                               {"role": "user", "content": ctx + hist}], "react", "s2", 800)
        if a.get("action") != "sql" or not a.get("sql"):
            break
        obs = run_sql(con, str(a["sql"]))
        errs += obs.startswith("ERROR")
        store[str(s + 1)] = obs[:RESULT_CHARS]
        hist += f"\nACTION {s + 1}: {a['sql']}\nOBSERVATION {s + 1}:\n{obs[:RESULT_CHARS]}"
    out = m.call_json([{"role": "system", "content": "Write the final answer. " + OUT_SPEC.replace("result ids", "observation numbers")},
                             {"role": "user", "content": ctx + "\nRESULTS" + hist}], "react_final", "s2", 3500)
    claims = _claims(out, store)
    return {"insights": [c["text"] for c in claims], "claims": claims, "summary": out.get("summary", ""),
            "confidence": conf01(out.get("confidence")), "steps": hist.count("ACTION "), "queries": len(store),
            "sql_errors": errs, "sql_errors_first_try": errs, "evidence_store": store}


ERR_CHARS = 600  # fix B6: full DuckDB error incl. "Did you mean" / LINE context (baseline: 200)
REPAIR_SYS = "Fix this DuckDB SQL query. Reply with JSON only: {\"sql\": str}."


def repair_prompt(ctx: str, tables: list[str], question: str, sql: str, err: str, tried: list | None = None) -> str:
    """SQL repair prompt (fix B6): the only DuckDB tables are named explicitly (the planner kept using table names
    from the dataset description, e.g. `incidents`, `alm_hardware` -> Catalog Error) and the error is passed in full."""
    return (ctx + f"\nTHE ONLY TABLES ARE: {', '.join(tables)} (names in the dataset description are NOT table names; "
            "use the column names exactly as in SCHEMA; DuckDB dialect: use quantile_cont instead of PERCENTILE_CONT, "
            "CAST VARCHAR timestamps before comparing)."
            + f"\nQUESTION: {question}\nSQL: {sql}\n{err}"
            + ("\nTHESE QUERIES ALREADY FAILED - do NOT return any of them again and do not reuse the construct named in the error; "
               "if unsure, write a SIMPLER query (fewer joins, no window functions):\n" + "\n".join(f"- {t['sql']}  -> {t['error'][:160]}" for t in tried) if tried else ""))


def agent_markov(task, con, tables, m: Meter, use_nv: bool = False, use_rerank: bool = False, ctl=None) -> dict:
    """agent + Markovian control (bench/markov.py): SQL repair only for repairable error classes, evaluator
    skipped when evidence is sufficient or the last round added nothing, gate rewrite only when expected to pay,
    optional deeper run (3 rounds + bigger Writer) for items the NVIDIA classifier rates hard. Same Traceability Check."""
    from .markov import Controller, load_features
    ctl = ctl or Controller(use_nv, load_features("insightbench") if use_nv else None, "insightbench")  # verify-v2 passes a policy subclass
    max_rounds, writer_model = ctl.insight_rounds(task["id"])
    sch = schema(con, tables)
    ctx = _context(task, sch)
    plan = m.call_json([{"role": "system", "content": "You are the Planner of a root-cause analytics agent. Decompose the goal into analysis questions, each answered by one DuckDB SQL query over the given tables. Include diagnostic (why) questions. Reply with JSON only: {\"steps\": [{\"question\": str, \"sql\": str}]} (max 6)."},
                              {"role": "user", "content": ctx}], "plan", "s2", 1500)
    steps, results = list(plan.get("steps") or [])[:6], {}
    for rnd in range(max_rounds):
        ok_before = sum(usable(r["result"]) for r in results.values())
        for s in steps:
            qid = f"q{len(results) + 1}"
            sql = str(s.get("sql", "") or "")
            res, first_err, prev, att = run_sql(con, sql, ERR_CHARS), None, None, 0
            tried, repeat = [], False
            while res.startswith("ERROR") and ctl.sql_repair(res, att, prev, repeat_sql=repeat):
                first_err, prev, att = first_err or res, res, att + 1
                tried.append({"sql": sql, "error": res})
                fx = m.call_json([{"role": "system", "content": REPAIR_SYS},
                                        {"role": "user", "content": repair_prompt(ctx, tables, s.get("question", ""), sql, res, tried)}], "sqlfix", "s1", 600)
                if not fx.get("sql"):
                    break
                if sql_key(fx["sql"]) in {sql_key(t["sql"]) for t in tried}:  # trace-fix 5: identical repeat -> never re-run
                    repeat = True
                    continue
                sql = str(fx["sql"])
                res = run_sql(con, sql, ERR_CHARS)
            if res.startswith("ERROR") and not first_err:
                first_err = res
            results[qid] = {"question": s.get("question", ""), "sql": sql, "result": res, "first_error": first_err}
        n_ok = sum(usable(r["result"]) for r in results.values())
        n_err = sum(r["result"].startswith("ERROR") for r in results.values())
        n_empty = len(results) - n_ok - n_err
        if not ctl.requery(rnd, n_ok, n_err, n_ok - ok_before, max_rounds, n_empty):
            break
        ev = m.call_json([{"role": "system", "content": "You are the Evidence Evaluator. Given the goal and the query results, decide whether the evidence is sufficient to explain WHY, or propose follow-up queries (drill-downs, comparisons, fixes for failed SQL). Reply with JSON only: {\"sufficient\": bool, \"new_steps\": [{\"question\": str, \"sql\": str}]} (max 4)."},
                                {"role": "user", "content": ctx + "\nRESULTS\n" + _fmt(results)}], "evaluate", "s1", 1200)
        steps = list(ev.get("new_steps") or [])[:4]
        if ev.get("sufficient") and n_ok == 0 and steps:  # trace-fix 2: never "sufficient" with 0 usable rows
            ctl._d("requery", {"round": rnd, "usable_results": 0, "evaluator_sufficient": True}, "OVERRIDE", "evaluator said sufficient but no result has rows; follow-up queries run")
        elif ev.get("sufficient") or not steps:
            break
    msgs = [{"role": "system", "content": "You are the Writer of a root-cause analytics agent. " + OUT_SPEC},
            {"role": "user", "content": ctx + "\nRESULTS\n" + _fmt(results)}]
    gate_log, prev, prev_bad = [], None, None
    view = {k: v["result"][:RESULT_CHARS] for k, v in results.items()}  # fix B9: gate sees exactly what the Writer and scorer see
    for g in range(GATE_ROUNDS + 1):
        out = m.call_json(msgs, "write", "s2", 3500, model=writer_model)
        draft = json.dumps(out)[:4000]  # fix B5: echo the model's own draft, not the gate-mutated copy (evidence was echoed back as [])
        ins = [i for i in (out.get("insights") or []) if isinstance(i, dict) and i.get("text")][:10]
        if not ins and prev:
            out, ins = prev
            gate_log.append({"round": g, "insights": 0, "note": "empty rewrite, kept previous draft"})
            break
        bad, uncited = [], []
        for i in ins:
            i["evidence"] = norm_ids(i.get("evidence"), results)
            un, nlog, contra = gate_ib_claim(i, view)
            i["unsupported_numbers"], i["number_log"], i["contradictions"] = un, nlog, contra
            if un or contra:
                bad.append(i)
            elif not i["evidence"] and nums(i["text"]):
                uncited.append(i)  # fix B8: numeric claim without a resolvable citation used to pass silently
        sum_un, _ = gate_claim(out.get("summary", ""), list(view.values()))
        gate_log.append({"round": g, "insights": len(ins), "failed": len(bad), "uncited": len(uncited), "summary_unsupported": sum_un, "drafts": [i["text"] for i in ins]})
        if not ctl.rewrite(len(ins), len(bad) + len(uncited), bool(sum_un), g, prev_bad, GATE_ROUNDS):
            break
        prev, prev_bad = (out, ins), len(bad) + len(uncited)
        msgs = msgs + [{"role": "assistant", "content": draft},
                       {"role": "user", "content": "Traceability check rejected these insights (numbers not present in the cited results, or a comparison/superlative "
                        "contradicted by the cited table): "
                        + json.dumps([{"text": i["text"], "unsupported": i["unsupported_numbers"], "contradicted_by_table": i.get("contradictions") or []} for i in bad] + ([{"summary": sum_un}] if sum_un else []))
                        + (". These insights cite no valid result id; cite the ids (e.g. [\"q2\"]) they come from: " + json.dumps([i["text"] for i in uncited]) if uncited else "")
                        + ". Rewrite. " + OUT_SPEC}]
    for i in ins:  # deterministic citation repair for still-uncited numeric claims (declared; never invents a citation)
        if not i["unsupported_numbers"] and not i["evidence"] and nums(i["text"]):
            cand = [k for k, v in view.items() if not v.startswith("ERROR") and any(x["status"] == "direct" for x in gate_claim(i["text"], [v])[1])]
            if cand and not gate_claim(i["text"], [view[k] for k in cand])[0]:
                i["evidence"], i["auto_cited"] = cand, True
    kept = [i for i in ins if not i["unsupported_numbers"] and not i.get("contradictions")]
    dropped = [{"text": i["text"], "evidence": i["evidence"], "unsupported": i["unsupported_numbers"], "contradictions": i.get("contradictions") or [],
                "reason": "numbers not in cited results nor recomputable from them" if i["unsupported_numbers"] else "comparison/superlative contradicted by the cited table"}
               for i in ins if i["unsupported_numbers"] or i.get("contradictions")]
    support, rerank_s = [], []
    if use_rerank:  # citation check: reranker p(cited evidence supports the claim); logged signal, never drops (uncalibrated here)
        from . import nv_rerank as NR
        import time as _t
        for i in kept:
            src = "\n".join(view[e][:1500] for e in i["evidence"]) or "(no citation)"
            try:
                t_r = _t.time(); p = NR.rank(i["text"], [src])[0]; rerank_s.append(round(_t.time() - t_r, 3))
            except Exception as e:  # audit #5: logged, not swallowed
                p = None
                m.parse_log.append({"tag": "rerank_error", "error": f"{type(e).__name__}: {str(e)[:100]}"})
            support.append(p)
            ctl._d("citation_check", {"claim": i["text"][:80], "cited": i["evidence"], "rerank_p": p},
                   "NO_SIGNAL" if p is None else ("WEAK" if p < 0.05 else "SUPPORTED"), "NVIDIA reranker (claim, cited results) support signal; logged only")
    return {"insights": [i["text"] for i in kept], "claims": [{"text": i["text"], "evidence": i["evidence"]} for i in kept],
            "summary": out.get("summary", ""), "confidence": conf01(out.get("confidence")),
            "confidence_det": det_confidence(results, kept, dropped),
            "conf_formula": "ib_det", "conf_inputs": {"n_q": len(results), "n_unusable": sum(not usable(r["result"]) for r in results.values()), "n_kept": len(kept), "n_dropped": len(dropped)},
            "empty_results": sum(is_empty_result(r["result"]) for r in results.values()),
            "dropped_by_gate": len(dropped), "dropped_claims": dropped, "gate": gate_log, "queries": len(results),
            "sql_errors": sum(r["result"].startswith("ERROR") for r in results.values()),
            "sql_errors_first_try": sum(1 for r in results.values() if r.get("first_error")),
            "evidence_store": {k: v["result"][:RESULT_CHARS] for k, v in results.items()},
                "queries_log": {k: {"question": v["question"], "sql": v["sql"], "first_error": v["first_error"]} for k, v in results.items()}, "decisions": ctl.log,
            "rerank_support": support, "rerank_seconds": rerank_s,
            "auto_cited": sum(1 for i in kept if i.get("auto_cited"))}


SYSTEMS = {"agent": agent, "agent_vr": lambda t, c, tb, m: agent(t, c, tb, m, vr=True), "rag": rag, "react": react,
           "agent_mk": lambda *a: agent_markov(*a, use_nv=False), "agent_mknv": lambda *a: agent_markov(*a, use_nv=True),
           "agent_mkr": lambda *a: agent_markov(*a, use_nv=True, use_rerank=True)}
from .verify2 import IB_SYSTEMS as _V2  # noqa: E402  verify-v2 configs (docs/VERIFY_V2.md)
SYSTEMS.update(_V2)


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
    r = m.call([{"role": "system", "content": G_EVAL_SYSTEM}, {"role": "user", "content": G_EVAL_TEMPLATE.format(answer=answer, gt_answer=gt)}], "judge", "s2", 50, model=JUDGE_MODEL)
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
