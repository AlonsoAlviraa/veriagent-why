"""Live smoke test for the NVIDIA API (free tier). One command: `python scripts/nvidia_smoke.py`.

- Reads NVIDIA_API_KEY from the process environment only. Never prints, logs or writes it.
- If the key is absent: prints SKIP and exits 0 (CI-safe).
- Tests FAST_MODEL first (default nemotron-3.5-lightning-30b-a3b), then REASONING_MODEL
  (default nemotron-3.5-super-vl-120b-a12b). Reports empty replies, HTTP errors (e.g. 500) and
  latency per model. Exit 1 if any model fails, so the caller knows to fall back.
- Writes a key-free JSON report to logs/nvidia_smoke.json.
"""
from __future__ import annotations
import json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
MODELS = [os.environ.get("FAST_MODEL") or "nvidia/nemotron-3.5-lightning-30b-a3b",
          os.environ.get("REASONING_MODEL") or "nvidia/nemotron-3.5-super-vl-120b-a12b"]
PROMPT = [{"role": "user", "content": 'Reply with JSON only: {"verdict": "supports"}'}]


def call(model: str, key: str) -> dict:
    payload = {"model": model, "messages": PROMPT, "max_tokens": 64, "temperature": 0}
    if model == MODELS[0]:  # S1 / lightning: thinking off, as in app/llm.py
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + "/chat/completions", data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + key})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            out = json.load(r)
        text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        ok = bool(text.strip())
        return {"model": model, "ok": ok, "status": 200, "empty_reply": not ok, "reply_preview": text.strip()[:80],
                "usage": out.get("usage"), "seconds": round(time.time() - t0, 2)}
    except urllib.error.HTTPError as e:
        return {"model": model, "ok": False, "status": e.code, "error": e.reason, "seconds": round(time.time() - t0, 2)}
    except Exception as e:  # network, timeout
        return {"model": model, "ok": False, "status": None, "error": type(e).__name__, "seconds": round(time.time() - t0, 2)}


def main() -> int:
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key:
        print("SKIP: NVIDIA_API_KEY is not set in the environment (nothing was called).")
        return 0
    print(f"NVIDIA_API_KEY present (value not shown). Base URL: {BASE}")
    results = []
    for m in MODELS:
        r = call(m, key)
        results.append(r)
        flag = "OK" if r["ok"] else ("EMPTY REPLY" if r.get("empty_reply") else f"FAIL status={r['status']} {r.get('error', '')}")
        print(f"{m}: {flag} in {r['seconds']} s")
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "nvidia_smoke.json").write_text(json.dumps({"base_url": BASE, "results": results}, indent=2))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
