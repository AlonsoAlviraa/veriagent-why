"""LLM-backed steps (provider nightshift|nvidia). Every output is parsed and validated against a fixed
schema; on failure the agent falls back to its deterministic path and the trace says so.
Numbers are never taken from the model: they come from SQL and pass the Claim Gate."""
from __future__ import annotations
import json, re
from concurrent.futures import ThreadPoolExecutor
from .. import llm

TAXONOMY = ["carrier_sla_breach", "supplier_cost_increase", "promotion_effect", "seasonality", "stockout", "none"]
HYP_CATALOG = {"H_carrier": "On-time drop concentrated in one carrier", "H_region": "On-time drop concentrated in one region",
               "H_promo": "A promotion active in the period caused the drop"}


def _json(text: str | None):
    if not text:
        raise ValueError("empty model response")
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        raise ValueError("no JSON in model response")
    return json.loads(m.group(1))


def plan(question: str, memory_context: str) -> tuple[list[str], dict]:
    r = llm.complete([{"role": "system", "content": "You plan a KPI-drop investigation. Reply with JSON only: {\"hypotheses\": [ids]} choosing 2-3 ids from the catalog."},
                      {"role": "user", "content": f"Question: {question}\nCatalog: {json.dumps(HYP_CATALOG)}\nMemory: {memory_context[:1500]}"}], "s2", 300)
    ids = [h for h in _json(r["content"]).get("hypotheses", []) if h in HYP_CATALOG]
    if not ids:
        raise ValueError("no valid hypothesis ids")
    return ids, r


def s1_scores(texts: list[str], question: str) -> tuple[list[float], list[dict]]:
    def one(t):
        r = llm.complete([{"role": "system", "content": "Rate how relevant this evidence chunk is to the question. Reply with JSON only: {\"score\": number between 0 and 1}."},
                          {"role": "user", "content": f"Question: {question}\nChunk: {t[:1200]}"}], "s1", 30)
        s = float(_json(r["content"])["score"])
        return max(0.0, min(1.0, s)), r
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, texts))
    return [s for s, _ in res], [r for _, r in res]


def verdict(hyp_text: str, stats: dict) -> tuple[str, dict]:
    r = llm.complete([{"role": "system", "content": "You verify one hypothesis against computed statistics. Reply with JSON only: {\"verdict\": \"supports\"|\"refutes\"|\"gap\"}."},
                      {"role": "user", "content": f"Hypothesis: {hyp_text}\nStatistics (from SQL): {json.dumps(stats, default=str)}"}], "s1", 30)
    v = _json(r["content"]).get("verdict")
    if v not in ("supports", "refutes", "gap"):
        raise ValueError(f"invalid verdict {v!r}")
    return v, r


def label(causes: list[dict]) -> tuple[str, dict]:
    r = llm.complete([{"role": "system", "content": f"Pick the top cause label. Reply with JSON only: {{\"label\": one of {TAXONOMY}}}."},
                      {"role": "user", "content": f"Supported causes (with computed contributions): {json.dumps(causes, default=str)}"}], "s2", 60)
    lab = _json(r["content"]).get("label")
    if lab not in TAXONOMY:
        raise ValueError(f"label {lab!r} not in taxonomy")
    return lab, r


def narrative(claims: list[dict], discarded: list[dict]) -> tuple[str, dict]:
    r = llm.complete([{"role": "system", "content": "Write a 3-sentence executive summary for a decision memo. Use ONLY the facts and numbers given. Do not add any other number."},
                      {"role": "user", "content": json.dumps({"claims": [c["text"] for c in claims], "discarded": discarded}, default=str)}], "s2", 300)
    if not r["content"] or not r["content"].strip():
        raise ValueError("empty model response")
    return r["content"].strip(), r
