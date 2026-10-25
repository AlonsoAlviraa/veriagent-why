"""TAT-QA adapter (hybrid table + text financial QA) -> thin VeriAgent Why path.

- agent: Evidence step (model quotes the cells/sentences it uses and gives an arithmetic expression)
  -> deterministic Claim Gate: every quote must occur in the context, every number in the expression
  must be a context number, and eval(expression) must equal the answer. On failure, one feedback
  round (max 2 gate rounds); the final answer is then kept but counted as gate-failed.
- rag:   BM25 top paragraphs + full table, one answer call. No checks.
- react: ReAct with a calculator tool (up to 4 steps), then answer. No checks.
Scoring: official TAT-QA scorer (tatqa_metric.TaTQAEmAndF1, downloaded) + our 'unsupported-number
rate', applied identically to every system (see `traceable`).
"""
from __future__ import annotations
import ast, itertools, json, operator, re, sys
from pathlib import Path
from app.bm25 import bm25
from .common import nums, supported
from .llmio import Meter, parse_json
from .tat_post import flatten, postprocess
from .common import conf01

SCALES = ["", "thousand", "million", "billion", "percent"]


def items(path: Path) -> list[dict]:
    out = []
    for doc in json.loads(Path(path).read_text()):
        for q in doc["questions"]:
            out.append({"id": q["uid"], "doc": doc, "q": q})
    return out


def table_md(t: list[list[str]]) -> str:
    return "\n".join("| " + " | ".join(c.strip() for c in row) + " |" for row in t)


def context(doc: dict, paras: list[dict] | None = None) -> str:
    ps = paras if paras is not None else sorted(doc["paragraphs"], key=lambda p: p["order"])
    return "TABLE\n" + table_md(doc["table"]["table"]) + "\nPARAGRAPHS\n" + "\n".join(f"[P{p['order']}] {p['text']}" for p in ps)


ANS = ('Reply with JSON only: {"answer": a string, or a list of strings for multi-span answers, or a number, '
       '"scale": one of ' + json.dumps(SCALES) + ', "expression": arithmetic expression over context numbers if computed else "", '
       '"evidence": [verbatim table cells or sentence fragments you used], "confidence": your probability 0-1 that the answer is exactly right}. '
       'RULES (TAT-QA conventions): 1) "scale": if the figure (or the figures it is computed from) comes from a table or sentence '
       'stated "in thousands"/"in millions"/"$ million" etc, use that scale, also for differences, sums and averages of such figures; '
       'percentages, percentage changes and ratios -> "percent"; counts, years and plain text -> "". Do not repeat the scale word inside "answer". '
       '2) Round computed answers to 2 decimal places. Keep the sign (decreases are negative). Write numbers without $ or commas. '
       '3) For text/span answers copy the SHORTEST exact span from the context that answers the question, not the whole sentence; '
       'for "respective"/multiple values return a list of strings.')

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos}


def safe_eval(expr: str) -> float:
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("unsupported expression")
    return ev(ast.parse(expr.replace(",", "").replace("$", "").replace("%", ""), mode="eval"))


def _norm(s: str) -> str:
    return re.sub(r"[\s$,()]+", " ", str(s).lower()).strip()


def gate(out: dict, ctx: str) -> list[str]:
    reasons, nctx, cnums = [], _norm(ctx), nums(ctx)
    for e in out.get("evidence") or []:
        if _norm(e) and _norm(e) not in nctx:
            reasons.append(f"evidence not found in context: {str(e)[:80]}")
    expr, ans = str(out.get("expression") or "").strip(), out.get("answer")
    if expr:
        for v in nums(expr):
            if v not in (100, 1000, 1e6) and not supported(abs(v), [abs(c) for c in cnums], free_small_ints=True):  # 100/1000 = percent/scale constants
                reasons.append(f"expression number {v} not in context")
        try:
            val = safe_eval(expr)
            a = nums(str(ans))
            if a and abs(a[0] - val) > max(0.01, 0.006 * abs(val)) and abs(a[0] - val * 100) > max(0.01, 0.006 * abs(val * 100)):
                reasons.append(f"answer {a[0]} != expression value {round(val, 4)}")
        except Exception:
            reasons.append("expression does not evaluate")
    elif nums(str(ans)) and not traceable(str(ans), ctx):
        reasons.append("numeric answer not in context and no expression given")
    return reasons


def traceable(answer: str, ctx: str) -> bool:
    """System-agnostic check used for the unsupported-number rate: every number in the answer must
    be a context number, or the result of one +,-,*,/ or percentage change over two context numbers,
    or the mean of two (within rounding). Non-numeric answers are out of scope (True)."""
    a = nums(answer)
    if not a:
        return True
    c = sorted(set(abs(x) for x in nums(ctx)))[:120]
    derived = list(c)
    for x, y in itertools.permutations(c, 2):
        derived += [x + y, x - y, x * y, (x + y) / 2]
        if y:
            derived += [x / y, (x - y) / y]
    return all(supported(abs(v), derived, free_small_ints=True) for v in a)


def agent(it: dict, m: Meter) -> dict:
    doc, q = it["doc"], it["q"]
    ctx = context(doc)
    msgs = [{"role": "system", "content": "You are VeriAgent Why's evidence step. Answer only from the context; quote your evidence. " + ANS},
            {"role": "user", "content": ctx + "\nQUESTION: " + q["question"]}]
    log = []
    for g in range(2):
        out = parse_json(m.call(msgs, "tat_agent", "s2", 600)) or {}
        reasons = gate(out, ctx)
        log.append({"round": g, "reasons": reasons})
        if not reasons:
            break
        msgs = msgs + [{"role": "assistant", "content": json.dumps(out)[:2000]},
                       {"role": "user", "content": "Claim gate rejected: " + "; ".join(reasons) + ". Fix and answer again. " + ANS}]
    p = _pred(out, it)
    # deterministic confidence (declared in docs/BENCHMARKS.md): gate outcome x traceability, no model input
    det = (0.8 if len(log) == 1 else 0.55) if not reasons else 0.2
    if not traceable(str(p["answer"]), ctx):
        det = min(det, 0.1)
    return {**p, "gate_passed": not reasons, "gate": log, "confidence_det": det}


def rag(it: dict, m: Meter, k: int = 3) -> dict:
    doc, q = it["doc"], it["q"]
    ps = doc["paragraphs"]
    sc = bm25([p["text"] for p in ps], q["question"])
    top = [ps[i] for i in sorted(range(len(ps)), key=lambda i: -sc[i])[:k]]
    out = parse_json(m.call([{"role": "system", "content": "Answer from the context. " + ANS},
                             {"role": "user", "content": context(doc, top) + "\nQUESTION: " + q["question"]}], "tat_rag", "s2", 600)) or {}
    return _pred(out, it)


def react(it: dict, m: Meter, max_steps: int = 4) -> dict:
    doc, q = it["doc"], it["q"]
    ctx = context(doc) + "\nQUESTION: " + q["question"]
    hist = ""
    for s in range(max_steps):
        a = parse_json(m.call([{"role": "system", "content": "You are a ReAct analyst with one tool: calc (arithmetic). Each turn reply with JSON only: {\"thought\": str, \"action\": \"calc\", \"input\": expression} or {\"action\": \"final\"}."},
                               {"role": "user", "content": ctx + hist}], "tat_react", "s2", 400)) or {}
        if a.get("action") != "calc":
            break
        try:
            obs = str(round(safe_eval(str(a.get("input", ""))), 6))
        except Exception as e:
            obs = f"error {type(e).__name__}"
        hist += f"\nACTION {s + 1}: calc({a.get('input')})\nOBSERVATION {s + 1}: {obs}"
    out = parse_json(m.call([{"role": "system", "content": "Give the final answer. " + ANS},
                             {"role": "user", "content": ctx + hist}], "tat_react_final", "s2", 600)) or {}
    return _pred(out, it)


def _pred(out: dict, it: dict | None = None) -> dict:
    """Raw model answer (flattened: fixes list-of-dicts TypeError) + deterministic scale/format post-step,
    applied identically to every system. Gold is never read here."""
    a = flatten(out.get("answer", ""))
    sc = out.get("scale") if out.get("scale") in SCALES else ""
    ev = out.get("evidence") or []
    ev = [str(e) for e in (flatten(ev) if isinstance(ev, (list, dict)) else [ev])]
    raw = {"answer": a, "scale": sc, "expression": str(out.get("expression", "") or "")}
    post = postprocess(raw, it["q"]["question"], it["doc"]) if it else raw
    return {**post, "raw": raw, "evidence": ev, "confidence": conf01(out.get("confidence"))}


SYSTEMS = {"agent": agent, "rag": rag, "react": react}


def official_scores(data_dir: Path, gold_items: list[dict], preds: dict[str, list]) -> dict:
    """Run the official TaTQAEmAndF1 (downloaded tatqa_metric.py) over exactly the scored items."""
    sys.path.insert(0, str(data_dir))
    import tatqa_metric  # noqa: E402  (official, MIT)
    em = tatqa_metric.TaTQAEmAndF1()
    for it in gold_items:
        a, s = preds.get(it["id"], [None, None])
        em(ground_truth=it["q"], prediction=a, pred_scale=s)
    g_em, g_f1, g_scale, _ = em.get_overall_metric()
    return {"em": round(g_em, 4), "f1": round(g_f1, 4), "scale_acc": round(g_scale, 4)}


def item_em(data_dir: Path, it: dict, pred: dict) -> tuple[float, float]:
    sys.path.insert(0, str(data_dir))
    import tatqa_metric
    em = tatqa_metric.TaTQAEmAndF1()
    em(ground_truth=it["q"], prediction=pred.get("answer"), pred_scale=pred.get("scale"))
    e, f, _, _ = em.get_overall_metric()
    return e, f
