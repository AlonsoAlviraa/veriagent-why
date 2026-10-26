"""LLM-backed steps (provider nightshift|nvidia). Every output is parsed and validated against a fixed
schema; on failure the agent falls back to its deterministic path and the trace says so.
Numbers are never taken from the model: they come from SQL and pass the Traceability Check."""
from __future__ import annotations
import json, re
from concurrent.futures import ThreadPoolExecutor
from .. import llm

TAXONOMY = ["carrier_sla_breach", "supplier_cost_increase", "promotion_effect", "seasonality", "stockout", "none"]
HYP_CATALOG = {"H_carrier": "On-time drop concentrated in one carrier", "H_region": "On-time drop concentrated in one region",
               "H_promo": "A promotion active in the period caused the drop",
               "H_seasonal": "A broad rise across almost all segments (calendar/seasonal pattern)"}



def _agent_call(agent: str, *a, **k):
    """Every model call carries the name of the agent that made it (written to the Nightshift receipt)."""
    return llm.complete(*a, agent=agent, **k)

def _json(text: str | None):
    if not text:
        raise ValueError("empty model response")
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        raise ValueError("no JSON in model response")
    return json.loads(m.group(1))


def plan(question: str, memory_context: str) -> tuple[list[str], dict]:
    r = _agent_call("planner", [{"role": "system", "content": "You plan a KPI-drop investigation. Reply with JSON only: {\"hypotheses\": [ids]} choosing 3-5 competing ids from the catalog, most likely first."},
                      {"role": "user", "content": f"Question: {question}\nCatalog: {json.dumps(HYP_CATALOG)}\nMemory: {memory_context[:1500]}"}], "s2", 300)
    ids = [h for h in _json(r["content"]).get("hypotheses", []) if h in HYP_CATALOG]
    if not ids:
        raise ValueError("no valid hypothesis ids")
    return ids, r


def s1_scores(texts: list[str], question: str) -> tuple[list[float], list[dict]]:
    batch_sz = max(1, int(llm.env("S1_FILTER_BATCH_SIZE", "5")))
    all_scores, all_meta = [], []
    for start in range(0, len(texts), batch_sz):
        sub = texts[start:start + batch_sz]
        numbered = "\n".join(f"[{i}] {c[:450]}" for i, c in enumerate(sub))
        r = _agent_call("s1_filter", [{"role": "system", "content": (
            f"Rate how relevant each evidence chunk [0..{len(sub)-1}] is to the question. "
            f"Reply with JSON only: {{\"scores\": [array of {len(sub)} numbers between 0 and 1 in order]}}.")},
            {"role": "user", "content": f"Question: {question}\nChunks:\n{numbered}"}], "s1", min(512, 20 * len(sub) + 64))
        d = _json(r["content"])
        arr = d.get("scores") if isinstance(d, dict) else d if isinstance(d, list) else None
        if isinstance(arr, list) and arr:
            vals = [max(0.0, min(1.0, float(x["score"] if isinstance(x, dict) and "score" in x else x))) for x in arr]
            vals = (vals + [vals[-1]] * len(sub))[:len(sub)]
        elif isinstance(d, dict) and "score" in d:
            vals = [max(0.0, min(1.0, float(d["score"])))] * len(sub)
        else:
            raise ValueError("invalid s1_scores response")
        all_scores.extend(vals)
        all_meta.append(r)
    return all_scores, all_meta


def verdict(hyp_text: str, stats: dict) -> tuple[str, dict]:
    r = _agent_call("evidence_evaluator", [{"role": "system", "content": "You verify one hypothesis against computed statistics. Reply with JSON only: {\"verdict\": \"supports\"|\"refutes\"|\"gap\"}."},
                      {"role": "user", "content": f"Hypothesis: {hyp_text}\nStatistics (from SQL): {json.dumps(stats, default=str)}"}], "s1", 30)
    v = _json(r["content"]).get("verdict")
    if v not in ("supports", "refutes", "gap"):
        raise ValueError(f"invalid verdict {v!r}")
    return v, r


def label(causes: list[dict]) -> tuple[str, dict]:
    r = _agent_call("cause_analyst", [{"role": "system", "content": f"Pick the top cause label. Reply with JSON only: {{\"label\": one of {TAXONOMY}}}."},
                      {"role": "user", "content": f"Supported causes (with computed contributions): {json.dumps(causes, default=str)}"}], "s2", 60)
    lab = _json(r["content"]).get("label")
    if lab not in TAXONOMY:
        raise ValueError(f"label {lab!r} not in taxonomy")
    return lab, r


def narrative(claims: list[dict], discarded: list[dict]) -> tuple[str, dict]:
    r = _agent_call("writer", [{"role": "system", "content": "Write a 3-sentence executive summary for a decision memo. Use ONLY the facts and numbers given. Do not add any other number."},
                      {"role": "user", "content": json.dumps({"claims": [c["text"] for c in claims], "discarded": discarded}, default=str)}], "s2", 300)
    if not r["content"] or not r["content"].strip():
        raise ValueError("empty model response")
    return r["content"].strip(), r


def retrieval_step(question: str, hypothesis: str, gap: str, observations: str, tools: dict, values: dict) -> tuple[dict, dict]:
    """Agentic Retriever step (S1, thinking off). Output schema:
    {"sufficient": bool, "tool": one of tools | null, "args": {...}, "why": str}. Validated again by the
    retriever's whitelist; the model never writes SQL."""
    r = _agent_call("retriever", [{"role": "system", "content": (
        "You are the retrieval agent of a KPI root-cause investigation. For ONE hypothesis, decide whether the evidence "
        "gathered so far is sufficient to test it; if not, choose ONE next tool call that would best confirm or refute it "
        "(e.g. drill into the most suspicious segment or date range, or search complaint text with a reformulated query). "
        "You cannot write SQL. Reply with JSON only: {\"sufficient\": true|false, \"tool\": name|null, \"args\": {}, \"why\": \"<15 words\"}.")},
        {"role": "user", "content": f"Question: {question}\nHypothesis: {hypothesis}\nOpen gap from evaluator: {gap or 'none'}\n"
                                    f"Tools: {json.dumps(tools)}\nValid values: {json.dumps(values)}\nEvidence so far: {observations[:1800]}"}], "s1", 220)
    d = _json(r["content"])
    if not isinstance(d, dict) or "sufficient" not in d:
        raise ValueError("bad retrieval decision schema")
    if d.get("tool") is not None and not isinstance(d.get("tool"), str):
        raise ValueError("tool must be a string")
    return {"sufficient": bool(d["sufficient"]), "tool": d.get("tool"), "args": d.get("args") if isinstance(d.get("args"), dict) else {},
            "why": str(d.get("why", ""))[:200]}, r
