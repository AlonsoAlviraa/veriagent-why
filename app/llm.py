"""Provider switch: nightshift | nvidia | sample.

- nightshift: Meterless Nightshift local OpenAI-compatible server (NIGHTSHIFT_BASE_URL).
- nvidia: NVIDIA API (NVIDIA_BASE_URL, NVIDIA_API_KEY from env; never logged).
- sample: offline; agents use their deterministic rule-based path and no model is called.
Nightshift is the primary provider: pinning + receipts in app/nightshift.py. LLM_FALLBACK=nvidia enables a logged fallback.
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


def complete(messages: list[dict], tier: str = "s2", max_tokens: int = 1024, purpose: str = "", agent: str = "") -> dict:
    """One model call. On nightshift every call writes a receipt (logs/receipts-<run_id>.jsonl) and the routed
    model must match the pin (app.nightshift.PinMismatch otherwise). If Nightshift is unreachable/times out/5xx
    and LLM_FALLBACK=nvidia, the call goes to NVIDIA and the receipt says fallback=true with the reason."""
    p = provider()
    if p == "sample":
        return {"provider": "sample", "model": None, "content": None}
    if p == "nightshift":
        from . import nightshift as NS
        import time
        t0 = time.time()
        msgs, truncated = NS.bound_messages(messages)
        body = NS.body(tier, msgs, max_tokens)
        import uuid
        client_rid = uuid.uuid4().hex  # sent as X-Request-Id; Nightshift 1.2.7 returned request_id=null, so we keep our own id too
        rec = {"provider": "nightshift", "tier": tier, "agent": agent or None, "purpose": purpose or agent, "client_request_id": client_rid, "requested": body["model"], "pin": NS.pin(tier),
               "max_tokens": body["max_tokens"], "prompt_chars": sum(len(m.get("content") or "") for m in msgs),
               "truncated": truncated, "fallback": False}
        base = env("NIGHTSHIFT_BASE_URL", "http://127.0.0.1:8088/v1")
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers={**NS.headers(), "X-Request-Id": client_rid})
        try:
            out = _post(req, _bounded_timeout(int(env(f"NIGHTSHIFT_TIMEOUT_{tier.upper()}_S", str(NS.TIMEOUT_S[tier])))), p)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = _err_meta(e)
            fb = env("LLM_FALLBACK", "none").lower()
            if fb != "nvidia" or (isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429):
                NS.write_receipt({**rec, **err, "ok": False, "latency_s": round(time.time() - t0, 3)})
                raise
            r = _complete_nvidia(messages, tier, max_tokens)
            NS.write_receipt({**rec, "ok": True, "fallback": True, "fallback_provider": "nvidia", "fallback_reason": err,
                              "routed_model": r["model"], "pin_ok": None, "latency_s": round(time.time() - t0, 3),
                              "usage": r.get("usage"), "finish_reason": r.get("finish_reason")})
            return {**r, "fallback": True, "fallback_reason": err.get("error")}
        meta = NS.meta_of(out)
        ok = NS.pin_ok(tier, meta["routed_model"])
        ch = (out.get("choices") or [{}])[0]
        NS.write_receipt({**rec, **meta, "response_id": out.get("id"), "ok": ok, "pin_ok": ok, "latency_s": round(time.time() - t0, 3),
                          "usage": out.get("usage"), "finish_reason": ch.get("finish_reason")})
        if not ok and NS.enforce():
            raise NS.PinMismatch(f"{tier}: Nightshift routed {meta['routed_model']!r}, pinned {NS.pin(tier)!r} "
                                 f"(request_id {meta['request_id']})")
        return {"provider": "nightshift", "model": meta["routed_model"], "requested_model": body["model"],
                "request_id": meta["request_id"], "routed_model": meta["routed_model"],
                "content": clean_content((ch.get("message") or {}).get("content")),
                "usage": out.get("usage"), "finish_reason": ch.get("finish_reason"), "fallback": False}
    if p == "nvidia":
        return _complete_nvidia(messages, tier, max_tokens)
    raise ValueError(f"unknown LLM_PROVIDER {p!r}")


def _bounded_timeout(t: float) -> float:
    left = remaining()
    if left is not None:
        if left <= 1:
            raise TimeoutError("run deadline reached (TIMEOUTS run_s)")
        t = min(t, left)
    return t


def _err_meta(e) -> dict:
    d = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    if isinstance(e, urllib.error.HTTPError):
        d["http_status"] = e.code
        try:
            j = json.loads(e.read() or b"{}")
            d["error_code"] = (j.get("error") or {}).get("code")
            from .nightshift import meta_of
            d.update({k: v for k, v in meta_of(j).items() if v is not None})
        except Exception:
            pass
    return d


def _complete_nvidia(messages, tier, max_tokens):
    base, key = env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"), env("NVIDIA_API_KEY")
    model = MODELS[tier]
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if tier == "s1" or env("NVIDIA_S2_THINKING", "off").lower() != "on":
        # S1 always runs with thinking off (ARCH v6.1): with thinking on, Nemotron lightning spends the
        # whole max_tokens budget in reasoning_content and returns empty content (finish_reason=length).
        # S2 thinking is off by default too: on the free endpoint, super-vl with thinking on exceeded a
        # 120 s timeout for a short planner prompt, vs ~16 s with it off. NVIDIA_S2_THINKING=on to enable.
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    out = _post(req, _bounded_timeout(TIMEOUTS["model_s"]), "nvidia")
    return {"provider": "nvidia", "model": model, "content": clean_content(out["choices"][0]["message"].get("content")),
            "usage": out.get("usage"), "finish_reason": out["choices"][0].get("finish_reason")}


_LAST = [0.0]


def _post(req, timeout, p):
    """POST with a client-side pacer (NVIDIA free tier is rate limited; MODEL_MIN_INTERVAL_S, default
    1.6 s on nvidia) and up to 3 retries on 429/5xx with backoff (Retry-After honoured)."""
    import time
    gap = float(env("MODEL_MIN_INTERVAL_S", "1.6" if p == "nvidia" else "0"))
    max_attempts = int(env("LLM_MAX_ATTEMPTS", "4"))
    for attempt in range(max_attempts):
        wait = _LAST[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _LAST[0] = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            left = remaining()
            if (e.code != 429 and e.code < 500) or attempt == max_attempts - 1 or (left is not None and left < 5):
                raise
            ra = e.headers.get("Retry-After") if e.headers else None
            time.sleep(float(ra) if ra and ra.replace(".", "").isdigit() else 2 * 2 ** attempt)


def clean_content(text):
    """Drop any inline <think>...</think> block some templates emit before the answer."""
    if not text:
        return text
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "</think>" in text:  # Nemotron 3 Ultra via Nightshift emits reasoning with only the closing tag
        text = text.rsplit("</think>", 1)[1]
    return text.strip()
