"""Per-run token / cost / latency report (Observability box of the v6.2 diagram).

Built only from what the run measured: model-call usage returned by the provider, wall-clock latencies,
the S1 projected-vs-actual token counts and the Markovian engine's own token figures. Cost is not
invented: the NVIDIA free endpoint and the sample provider are reported as 0 EUR; Nightshift is metered
by Meterless and reported as "metered by Meterless (not visible to this app)". Optional per-model
EUR prices can be supplied with MODEL_PRICE_EUR_PER_MTOK='{"model": [in, out]}' (blank by default)."""
from __future__ import annotations
import json
from .config import env


def _prices() -> dict:
    try:
        return json.loads(env("MODEL_PRICE_EUR_PER_MTOK", "{}"))
    except ValueError:
        return {}


def build(calls: list[dict], provider: str, rounds: list[dict], markovian: dict, wall_s: float, deadline_hit: bool) -> dict:
    by: dict[str, dict] = {}
    prices = _prices()
    for c in calls:
        k = f"{c['agent']}|{c.get('model') or '-'}"
        b = by.setdefault(k, {"agent": c["agent"], "model": c.get("model"), "calls_ok": 0, "calls_failed": 0,
                              "prompt_tokens": 0, "completion_tokens": 0, "latency_s_sum": 0.0})
        b["calls_ok" if c["ok"] else "calls_failed"] += 1
        u = c.get("usage") or {}
        b["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
        b["completion_tokens"] += int(u.get("completion_tokens") or 0)
        # batched (parallel) calls share one wall-clock latency; count it once per batch
        b["latency_s_sum"] += (c.get("latency_s") or 0) / max(1, c.get("batch", 1))
    rows = list(by.values())
    for r in rows:
        r["latency_s_sum"] = round(r["latency_s_sum"], 3)
        p = prices.get(r["model"] or "")
        r["cost_eur"] = round((r["prompt_tokens"] * p[0] + r["completion_tokens"] * p[1]) / 1e6, 6) if p else None
    tot_p, tot_c = sum(r["prompt_tokens"] for r in rows), sum(r["completion_tokens"] for r in rows)
    if provider == "sample":
        cost = "0 EUR (sample provider: no model called)"
    elif provider == "nvidia":
        cost = "0 EUR on the NVIDIA free endpoint (rate-limited); list price not applied"
    else:
        cost = "metered by Meterless/Nightshift (not visible to this app)"
    if any(r["cost_eur"] is not None for r in rows):
        cost = f"{round(sum(r['cost_eur'] or 0 for r in rows), 6)} EUR at MODEL_PRICE_EUR_PER_MTOK prices"
    proj = sum(r["s1_projected_tokens"] for r in rounds)
    act = sum(r["s1_actual_tokens"] for r in rounds)
    return {"provider": provider, "wall_clock_s": round(wall_s, 3), "deadline_hit": deadline_hit,
            "model_calls": {"ok": sum(c["ok"] for c in calls), "failed": sum(not c["ok"] for c in calls)},
            "tokens": {"prompt": tot_p, "completion": tot_c, "total": tot_p + tot_c, "source": "provider usage field"},
            "by_agent_model": rows, "cost": cost,
            "s1_filter": {"projected": proj, "actual": act, "avoided": proj - act, "unit": "whitespace tokens (approx.)"},
            "markovian": {k: markovian.get(k) for k in ("status", "totalTokensUsed", "totalTokensSaved", "tokenLabel") if k in markovian}}


def to_md(r: dict) -> list[str]:
    L = ["", "## Run report (tokens, cost, latency)",
         f"- Provider: {r['provider']}" + ("; 8-min deadline hit" if r["deadline_hit"] else "") + " (wall clock and latencies: report JSON)",
         f"- Model calls: {r['model_calls']['ok']} ok, {r['model_calls']['failed']} fell back; tokens {r['tokens']['total']} "
         f"(prompt {r['tokens']['prompt']}, completion {r['tokens']['completion']})",
         f"- Cost: {r['cost']}",
         f"- S1 filter: {r['s1_filter']['projected']} projected vs {r['s1_filter']['actual']} sent ({r['s1_filter']['avoided']} avoided, {r['s1_filter']['unit']})"]
    L += [f"- {x['agent']} / {x['model']}: {x['calls_ok']} ok, {x['calls_failed']} failed, {x['prompt_tokens']}+{x['completion_tokens']} tok"
          for x in r["by_agent_model"]]
    return L
