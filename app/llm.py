"""Provider switch: nightshift | nvidia | sample.

- nightshift: Meterless Nightshift local OpenAI-compatible server (NIGHTSHIFT_BASE_URL).
- nvidia: NVIDIA API (NVIDIA_BASE_URL, NVIDIA_API_KEY from env; never logged).
- sample: offline; agents use their deterministic rule-based path and no model is called.
Day-1 status: agents run the deterministic path; live model calls are wired here but not yet used by agents.
"""
from __future__ import annotations
import json, urllib.request
from .config import env, provider, TIMEOUTS

MODELS = {"s2": env("REASONING_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b"),
          "s1": env("FAST_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")}


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
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    return {"provider": p, "model": model, "content": out["choices"][0]["message"]["content"],
            "usage": out.get("usage")}
