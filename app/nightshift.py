"""Nightshift (Meterless Runtime) as primary provider: model pinning, receipts, startup pin check.

Contract (Meterless Runtime provider contract v4): OpenAI-compatible /v1, Bearer token from
<stateDir>/proxy-token, headers meterless-app / meterless-scope. Every reply carries a `meterless`
block {request_id, requested_model, provider_model, routed_model, ...}; we write it verbatim (minus
anything secret) to logs/receipts-<run_id>.jsonl, one line per model call.

Pinning: S1 must be answered by Nemotron 3.5 Lightning 30B (reasoning off), S2 by Nemotron 3 Ultra
550B. If Nightshift routes any other model, the call raises PinMismatch and the run fails loudly
(it is NOT silently replaced by the deterministic path or by the fallback provider).
"""
from __future__ import annotations
import json, os, re, threading, time
from pathlib import Path
from .config import ROOT, env, log_dir

# Substring patterns (case/punctuation-insensitive) the routed model id must contain.
DEFAULT_PINS = {"s1": "nemotron-3.5-lightning-30b-a3b", "s2": "nemotron-3-ultra-550b-a55b"}
# Requested model per tier: exact ids from GET /v1/models (Nightshift 1.2.7). Routing modes such as meterless/fast
# are coerced to meterless/auto by the app policy and were observed routing to Nemotron 3.5 Bolt E4B, so tiers pin exact ids.
DEFAULT_REQUEST = {"s1": "nvidia/nemotron-3.5-lightning-30b-a3b", "s2": "nvidia/nemotron-3-ultra-550b-a55b"}
MAX_TOKENS = {"s1": 512, "s2": 2048}            # hard caps per call
TIMEOUT_S = {"s1": 180, "s2": 300}             # generous: 1.2.1 on Windows timed out full Planner/Critic calls
MAX_PROMPT_CHARS = 24000                        # bound the request body


class PinMismatch(RuntimeError):
    """Nightshift answered with a model other than the pinned one. Never caught by agent fallbacks."""


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", (s or "").lower())


def pin(tier: str) -> str:
    return env(f"NIGHTSHIFT_PIN_{tier.upper()}", DEFAULT_PINS[tier])


def request_model(tier: str) -> str:
    return env(f"NIGHTSHIFT_MODEL_{tier.upper()}", DEFAULT_REQUEST[tier])


def pin_ok(tier: str, routed: str | None) -> bool:
    return bool(routed) and _norm(pin(tier)) in _norm(routed)


def enforce() -> bool:
    """NIGHTSHIFT_PIN_ENFORCE=off only for offline mocks/the simulator (no meterless block); the receipt still says pin_ok=false."""
    return env("NIGHTSHIFT_PIN_ENFORCE", "on").lower() != "off"


def token() -> str:
    """NIGHTSHIFT_API_KEY, else <NIGHTSHIFT_STATE_DIR>/proxy-token. Never logged."""
    k = env("NIGHTSHIFT_API_KEY")
    if k:
        return k
    kf = env("NIGHTSHIFT_API_KEY_FILE")  # e.g. the local simulator's token file (app/nightshift_sim.py)
    if kf:
        return Path(kf).expanduser().read_text().strip()
    sd = env("NIGHTSHIFT_STATE_DIR") or (os.path.join(os.environ.get("LOCALAPPDATA", ""), "ai.meterless.runtime")
                                         if os.name == "nt" else os.path.expanduser("~/.meterless"))
    p = Path(sd) / "proxy-token"
    return p.read_text().strip() if p.exists() else ""


def bound_messages(messages: list[dict], limit: int | None = None) -> tuple[list[dict], bool]:
    """Truncate the longest message contents so the total stays under the cap. Returns (messages, truncated)."""
    limit = limit or int(env("NIGHTSHIFT_MAX_PROMPT_CHARS", str(MAX_PROMPT_CHARS)))
    msgs = [dict(m) for m in messages]
    total = sum(len(m.get("content") or "") for m in msgs)
    if total <= limit:
        return msgs, False
    over = total - limit
    for m in sorted(msgs, key=lambda m: -len(m.get("content") or "")):
        c = m.get("content") or ""
        cut = min(over, max(0, len(c) - 200))
        if cut:
            m["content"] = c[: len(c) - cut] + "\n[truncated]"
            over -= cut
        if over <= 0:
            break
    return msgs, True


def body(tier: str, messages: list[dict], max_tokens: int) -> dict:
    b = {"model": request_model(tier), "messages": messages, "max_tokens": min(max_tokens, MAX_TOKENS[tier]), "temperature": 0}
    if tier == "s1":  # reasoning off for Lightning: otherwise the budget goes to reasoning_content and content is empty
        b["chat_template_kwargs"] = {"enable_thinking": False}
        b["reasoning_effort"] = "none"
    elif env("NIGHTSHIFT_S2_THINKING", "off").lower() in ("off", "0", "false"):
        # Ultra with thinking on spent the whole 60/300-token budget on reasoning (finish_reason=length) in the
        # first live Nightshift run; with enable_thinking=false it answers directly (finish_reason=stop).
        b["chat_template_kwargs"] = {"enable_thinking": False}
    return b


def headers() -> dict:
    h = {"Content-Type": "application/json", "meterless-app": env("NIGHTSHIFT_APP", "veriagent-why"), "meterless-scope": "user"}
    k = token()
    if k:
        h["Authorization"] = f"Bearer {k}"
    return h


def meta_of(out: dict) -> dict:
    m = out.get("meterless") or {}
    return {k: m.get(k) for k in ("request_id", "requested_model", "provider_model", "routed_model", "mode", "app", "scope")}


# ---------- receipts ----------
_RUN = {"run_id": None, "dir": None}
_LOCK = threading.Lock()


def set_run(run_id: str | None, log_dir: Path | None = None) -> None:
    _RUN["run_id"], _RUN["dir"] = run_id, (log_dir or globals()["log_dir"]())


def receipts_path(run_id: str | None = None, log_dir: Path | None = None) -> Path:
    rid = run_id or _RUN["run_id"] or "adhoc"
    return Path(log_dir or _RUN["dir"] or globals()["log_dir"]()) / f"receipts-{rid}.jsonl"


def write_receipt(rec: dict) -> dict:
    rec = {"ts": round(time.time(), 3), "run_id": _RUN["run_id"] or "adhoc", **rec}
    p = receipts_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def check_pins(tiers=("s1", "s2")) -> list[dict]:
    """Startup check: one tiny real request per tier; raises PinMismatch unless routed_model matches the pin."""
    from . import llm
    res = []
    for t in tiers:
        r = llm.complete([{"role": "user", "content": "Reply with the single word OK."}], tier=t, max_tokens=8, purpose="pin_check")
        res.append({"tier": t, "routed_model": r.get("routed_model"), "pin": pin(t), "ok": True})
    return res


if __name__ == "__main__":  # python -m app.nightshift  -> live pin check, prints receipts (no secrets)
    from .config import load_dotenv
    load_dotenv()
    os.environ.setdefault("SAMPLE_MODE", "false"); os.environ.setdefault("LLM_PROVIDER", "nightshift")
    set_run("pincheck-" + time.strftime("%Y%m%d-%H%M%S"))
    try:
        print(json.dumps(check_pins(), indent=1)); print("receipts:", receipts_path())
    except PinMismatch as e:
        print("PIN MISMATCH:", e); print("receipts:", receipts_path()); raise SystemExit(2)
