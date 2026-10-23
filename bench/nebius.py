"""Nebius Token Factory client with a HARD, persistent, cross-process spend guard.

Nebius bills the user's card automatically past the promo balance and has no platform cap, so:
- every call is pre-checked against the worst case (conservative prompt estimate + max_tokens);
  if cumulative spend + in-flight reservations + worst case > NEBIUS_BUDGET_USD (default 20.0)
  the call is refused (NebiusBudgetExceeded) and bench.llmio falls back to NVIDIA free;
- actual cost (from returned usage) is booked in a ledger at NEBIUS_LEDGER
  (default ~/.veriagent/nebius_spend.json, outside the repo) under an exclusive flock;
  the reservation is held while the call is in flight so parallel processes cannot overshoot;
- if a call was sent but usage is unknown (timeout, 5xx), the worst case is booked;
- unknown models are refused (no price -> no call).
Prices: USD per 1M tokens (input, output), Nebius Token Factory published prices as given 2026-10-22.
"""
from __future__ import annotations
import fcntl, json, os, time, urllib.request, urllib.error
from contextlib import contextmanager
from pathlib import Path

BASE = "https://api.tokenfactory.nebius.com/v1"
PRICES = {
    "nvidia/Nemotron-3_5-Lightning": (0.06, 0.24),
    "nvidia/nemotron-3-super-120b-a12b": (0.30, 0.90),
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": (0.06, 0.24),
    "nvidia/Nemotron-3-Ultra-550b-a55b": (1.00, 3.00),
}
DEFAULT_MODEL = "nvidia/Nemotron-3_5-Lightning"


class NebiusBudgetExceeded(RuntimeError):
    pass


def budget() -> float:
    return float(os.environ.get("NEBIUS_BUDGET_USD") or 20.0)


def ledger_path() -> Path:
    return Path(os.environ.get("NEBIUS_LEDGER") or Path.home() / ".veriagent" / "nebius_spend.json")


def cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pi, po = PRICES[model]
    return (prompt_tokens * pi + completion_tokens * po) / 1e6


@contextmanager
def _locked():
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p) + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            d = json.loads(p.read_text()) if p.exists() else {"spent_usd": 0.0, "reserved": {}, "calls": 0, "entries": []}
            yield d
            tmp = Path(str(p) + ".tmp")
            tmp.write_text(json.dumps(d, indent=1))
            tmp.replace(p)
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def status() -> dict:
    with _locked() as d:
        return {"spent_usd": round(d["spent_usd"], 6), "reserved_usd": round(sum(d["reserved"].values()), 6),
                "calls": d["calls"], "budget_usd": budget(), "ledger": str(ledger_path())}


def reserve(model: str, est_prompt_tokens: int, max_tokens: int) -> str:
    if model not in PRICES:
        raise NebiusBudgetExceeded(f"no published price for {model!r}; refusing")
    worst = cost(model, est_prompt_tokens, max_tokens)
    rid = f"{os.getpid()}-{time.time_ns()}"
    with _locked() as d:
        committed = d["spent_usd"] + sum(d["reserved"].values())
        if committed + worst > budget():
            raise NebiusBudgetExceeded(f"Nebius budget {budget():.2f} USD would be exceeded (committed {committed:.4f} + worst {worst:.4f})")
        d["reserved"][rid] = worst
    return rid


def settle(rid: str, model: str, usage: dict | None, book_worst: bool) -> float:
    with _locked() as d:
        worst = d["reserved"].pop(rid, 0.0)
        if usage:
            c = cost(model, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
        else:
            c = worst if book_worst else 0.0
        d["spent_usd"] += c
        d["calls"] += 1
        d["entries"] = (d["entries"] + [{"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": model, "usd": round(c, 6), "usage": usage}])[-500:]
        return c


def complete(messages: list[dict], model: str | None = None, max_tokens: int = 1024, timeout: float = 180) -> dict:
    model = model or os.environ.get("NEBIUS_MODEL") or DEFAULT_MODEL
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        raise RuntimeError("NEBIUS_API_KEY not set")
    est = sum(len(m["content"]) for m in messages) // 3 + 50  # conservative (~3 chars/token)
    rid = reserve(model, est, max_tokens)
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if os.environ.get("NEBIUS_THINKING", "0") != "1":
        body["chat_template_kwargs"] = {"enable_thinking": False}  # same as app.llm for NVIDIA
    if os.environ.get("NEBIUS_JSON_MODE", "1") == "1" and any("JSON" in m["content"] for m in messages):
        body["response_format"] = {"type": "json_object"}  # Lightning without thinking often ignores "JSON only"
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    usage, book_worst = None, True
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
        usage = out.get("usage")
        ch = out["choices"][0]
        from app.llm import clean_content
        return {"provider": "nebius", "model": model, "content": clean_content(ch["message"].get("content")),
                "usage": usage, "finish_reason": ch.get("finish_reason")}
    except urllib.error.HTTPError as e:
        book_worst = e.code >= 500 or e.code == 408  # 4xx (auth, 429, bad request) are not billed
        raise
    finally:
        settle(rid, model, usage, book_worst)
