"""Provider switch: nightshift | nvidia | sample.

- nightshift: Meterless Nightshift local OpenAI-compatible server (NIGHTSHIFT_BASE_URL).
- nvidia: NVIDIA API (NVIDIA_BASE_URL, NVIDIA_API_KEY from env; never logged).
- sample: offline; agents use their deterministic rule-based path and no model is called.
Day-1 status: agents run the deterministic path; live model calls are wired here but not yet used by agents.
"""
from __future__ import annotations
import json, urllib.request, urllib.error
from .config import env, provider, TIMEOUTS

MODELS = {"s2": env("REASONING_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b"),
          "s1": env("FAST_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")}


_DEADLINE = [None]  # absolute epoch seconds for the current run (8-min cap); set by the orchestrator


def set_deadline(ts: float | None) -> None:
    _DEADLINE[0] = ts


def remaining() -> float | None:
    import time
    return None if _DEADLINE[0] is None else _DEADLINE[0] - time.time()


def complete(messages: list[dict], tier: str = "s2", max_tokens: int = 1024) -> dict:
    p = provider()
    if p == "sample":
        return {"provider": "sample", "model": None, "content": None}
    headers = {"Content-Type": "application/json"}
    model, timeout = MODELS[tier], TIMEOUTS["model_s"]
    if p == "nightshift":
        # Meterless Runtime provider contract: /v1 base, bearer token, meterless-app header, model ids are routing modes.
        base, key = env("NIGHTSHIFT_BASE_URL", "http://127.0.0.1:8088/v1"), env("NIGHTSHIFT_API_KEY")
        model = env("NIGHTSHIFT_MODEL_S1" if tier == "s1" else "NIGHTSHIFT_MODEL_S2", "meterless/auto")
        headers.update({"meterless-app": "veriagent-why", "meterless-scope": "user"})
        timeout = 180
    elif p == "nvidia":
        base, key = env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"), env("NVIDIA_API_KEY")
    else:
        raise ValueError(f"unknown LLM_PROVIDER {p!r}")
    if not base:
        raise RuntimeError(f"{p}: base URL not configured")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if p == "nvidia" and (tier == "s1" or env("NVIDIA_S2_THINKING", "off").lower() != "on"):
        # S1 always runs with thinking off (ARCH v6.1): with thinking on, Nemotron lightning spends the
        # whole max_tokens budget in reasoning_content and returns empty content (finish_reason=length).
        # S2 thinking is off by default too: on the free endpoint, super-vl with thinking on exceeded a
        # 120 s timeout for a short planner prompt, vs ~16 s with it off. NVIDIA_S2_THINKING=on to enable.
        body["chat_template_kwargs"] = {"enable_thinking": False}
    left = remaining()
    if left is not None:
        if left <= 1:
            raise TimeoutError("run deadline reached (TIMEOUTS run_s)")
        timeout = min(timeout, left)
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    out = _post(req, timeout, p)
    return {"provider": p, "model": model, "content": clean_content(out["choices"][0]["message"].get("content")),
            "usage": out.get("usage"), "finish_reason": out["choices"][0].get("finish_reason")}


_LAST = [0.0]


def _post(req, timeout, p):
    """POST with a client-side pacer (NVIDIA free tier is rate limited; MODEL_MIN_INTERVAL_S, default
    1.6 s on nvidia) and up to 3 retries on 429/5xx with backoff (Retry-After honoured)."""
    import time
    gap = float(env("MODEL_MIN_INTERVAL_S", "1.6" if p == "nvidia" else "0"))
    for attempt in range(4):
        wait = _LAST[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _LAST[0] = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            left = remaining()
            if (e.code != 429 and e.code < 500) or attempt == 3 or (left is not None and left < 5):
                raise
            ra = e.headers.get("Retry-After") if e.headers else None
            time.sleep(float(ra) if ra and ra.replace(".", "").isdigit() else 2 * 2 ** attempt)


def clean_content(text):
    """Drop any inline <think>...</think> block some templates emit before the answer."""
    if not text:
        return text
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
