"""Metered model I/O for benchmark runs.

- live: goes through app.llm.complete (same provider switch, same pacer, key from env, never logged).
- offline: a deterministic scripted fake (no network) so CI can exercise every code path.
Every call is counted against a hard budget (BudgetExceeded) and metered (calls, tokens, seconds).
"""
from __future__ import annotations
import os
import json, os, re, time


class BudgetExceeded(RuntimeError):
    pass


# Alonso's decision: every LLM-judge metric (InsightBench G-Eval + faithfulness) uses Super on Nebius, for all configs.
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "nvidia/nemotron-3-super-120b-a12b")


class Meter:
    def __init__(self, max_calls: int, offline: bool):
        self.max_calls, self.offline = max_calls, offline
        self.calls = self.prompt_tokens = self.completion_tokens = self.errors = 0
        self.seconds = 0.0
        self.last = None
        self.finish = []
        self.usd = 0.0
        self.providers = {}
        self.parse_failures, self.parse_log = 0, []
        # audit trace hook (docs/AUDIT_TRACE.md): one record per model call; AUDIT_TRACE=0 disables
        self.trace = os.environ.get("AUDIT_TRACE", "1") == "1"
        self.calls_log: list[dict] = []
        # trace-fix 6: per-item cache of identical deterministic calls (T=0). A Meter is created per item (bench/run.py),
        # so the cache never crosses items. Hits are NOT counted as calls and cost nothing; LLM_CACHE=0 disables.
        self.cache: dict[str, str] = {}
        self.cache_hits = 0

    def snapshot(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens, "model_seconds": round(self.seconds, 2), "errors": self.errors,
                "nebius_usd": round(self.usd, 6), "providers": self.providers,
                "finish_reasons": self.finish, "parse_failures": self.parse_failures, "cache_hits": self.cache_hits, "parse_log": self.parse_log[:10], "last_reply_head": (self.last or "")[:300], **({"trace_calls": self.calls_log} if self.trace else {})}

    def call_json(self, messages: list[dict], tag: str, tier: str = "s2", max_tokens: int = 800, model: str | None = None,
                  retries: int = 1) -> dict:
        """fix (audit #5): parse_json(...) or {} silently turned an unparseable reply into an empty answer.
        Now every failure is counted/logged in the meter and retried once with an explicit JSON-only nudge."""
        reply = self.call(messages, tag, tier, max_tokens, model=model)
        out = parse_json(reply)
        k = 0
        while out is None and k < retries:
            self.parse_failures += 1
            self.parse_log.append({"tag": tag, "retry": k + 1, "reply_head": (reply or "")[:120]})
            reply = self.call(messages + [{"role": "assistant", "content": (reply or "")[:1500]},
                                          {"role": "user", "content": "Your reply was not valid JSON. Reply again with ONE JSON object only, no prose, no code fences."}],
                              tag + "_json_retry", tier, max_tokens, model=model)
            out = parse_json(reply)
            k += 1
        if out is None:
            self.parse_failures += 1
            self.parse_log.append({"tag": tag, "retry": "gave_up", "reply_head": (reply or "")[:120]})
        return out or {}

    def call(self, messages: list[dict], tag: str, tier: str = "s2", max_tokens: int = 800, model: str | None = None) -> str:
        key = None
        if os.environ.get("LLM_CACHE", "1") == "1" and _temperature() == 0:
            import hashlib
            key = hashlib.sha256(json.dumps([messages, model, tier, max_tokens], sort_keys=True, default=str).encode()).hexdigest()
            if key in self.cache:
                self.cache_hits += 1
                if self.trace:
                    self.calls_log.append({"i": None, "tag": tag, "cached": True, "prompt_hash": "sha256:" + key[:16], "cost_usd": 0.0,
                                           "reply_head": self.cache[key][:600]})
                self.last = self.cache[key]
                return self.cache[key]
        out = self._call(messages, tag, tier, max_tokens, model)
        if key is not None:
            self.cache[key] = out
        return out

    def _call(self, messages: list[dict], tag: str, tier: str = "s2", max_tokens: int = 800, model: str | None = None) -> str:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"max_calls={self.max_calls} reached")
        self.calls += 1
        t = time.time()
        pt0, ct0, usd0, rec = self.prompt_tokens, self.completion_tokens, self.usd, None
        if self.trace:
            import hashlib
            ptxt = "\n".join(f"[{m['role']}] {m['content']}" for m in messages)
            rec = {"i": self.calls, "tag": tag, "requested_model": model, "prompt_hash": "sha256:" + hashlib.sha256(ptxt.encode()).hexdigest()[:16],
                   "prompt": ptxt[:int(os.environ.get("AUDIT_PROMPT_CHARS", "2000"))], "prompt_chars": len(ptxt),
                   **({"prompt_full": ptxt} if os.environ.get("AUDIT_FULL_PROMPTS", "1") == "1" and len(ptxt) > int(os.environ.get("AUDIT_PROMPT_CHARS", "2000")) else {})}
            self.calls_log.append(rec)
        try:
            if self.offline:
                out = fake(messages, tag)
                usage = {"prompt_tokens": sum(len(m["content"].split()) for m in messages), "completion_tokens": len(out.split())}
            else:
                r = _live(messages, tier, max_tokens, model)
                out, usage = r.get("content") or "", r.get("usage") or {}
                if r.get("logprobs") is not None:  # V9 only (nebius.LOGPROBS); kept in memory, not traced
                    self.__dict__.setdefault("lp_log", []).append({"tag": tag, "content": out, "lp": r["logprobs"]})
                self.finish.append(r.get("finish_reason"))
                pk = f'{r.get("provider")}:{r.get("model")}'
                self.providers[pk] = self.providers.get(pk, 0) + 1
                if r.get("provider") == "nebius" and usage:
                    from .nebius import cost
                    self.usd += cost(r["model"], int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
        except BudgetExceeded:
            raise
        except Exception as e:
            self.errors += 1
            if rec is not None:
                rec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            raise
        finally:
            self.seconds += time.time() - t
            if rec is not None:
                rec["latency_s"] = round(time.time() - t, 3)
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        self.last = out
        if rec is not None:
            rec.update({"model": None if self.offline else f'{r.get("provider")}:{r.get("model")}',
                        "prompt_tokens": self.prompt_tokens - pt0, "completion_tokens": self.completion_tokens - ct0,
                        "cost_usd": round(self.usd - usd0, 6), "reply_head": (out or "")[:600]})
        return out


def _temperature() -> float:
    try:
        from . import nebius
        return float(nebius.TEMPERATURE)
    except Exception:
        return 0.0


class NebiusHardStop(BaseException):
    """Raised with NEBIUS_STRICT=1 when the Nebius budget guard refuses a call; stops the whole run."""


def _live(messages, tier, max_tokens, model=None):
    """LLM_PROVIDER=nebius -> Nebius (hard spend guard); on NebiusBudgetExceeded fall back to NVIDIA free.
    Otherwise app.llm.complete. BENCH_SINGLE_MODEL=1 (default): one model for every step and system."""
    from app import llm
    if os.environ.get("BENCH_SINGLE_MODEL", "1") == "1":
        tier = "s2"
    if os.environ.get("LLM_PROVIDER") == "nebius":
        from . import nebius
        try:
            to = float(os.environ.get("MODEL_TIMEOUT_S") or 90)  # per-request timeout
            for attempt in range(3):  # transient errors (timeout, 429, 5xx): bounded retry with backoff
                try:
                    return nebius.complete(messages, model, max_tokens, to)  # model: per-call override (Markovian DEEP route), else NEBIUS_MODEL
                except nebius.NebiusBudgetExceeded:
                    raise
                except Exception as e:
                    code = getattr(e, "code", None)
                    if attempt == 2 or (code is not None and code not in (408, 429) and code < 500):
                        raise
                    time.sleep(5 * (attempt + 1))
        except nebius.NebiusBudgetExceeded as e:
            if os.environ.get("NEBIUS_STRICT") == "1":  # hard stop: never fall back, never overspend
                raise NebiusHardStop(str(e)) from e
            os.environ["LLM_PROVIDER"] = "nvidia"  # sticky fallback for the rest of the process
    return llm.complete(messages, tier, max_tokens)


def parse_json(text: str | None):
    """First JSON object in a model reply (tolerates ```json fences). None if absent."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    s = m.group(1) if m else text
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j > i:
        try:
            v = json.loads(s[i:j + 1])
            return v if isinstance(v, dict) else None
        except Exception:
            return None
    return None


# ---------------------------------------------------------------- offline fake (CI only)
def fake(messages: list[dict], tag: str) -> str:
    """Deterministic stand-in. It is NOT a model: it only returns well-formed replies so the
    harness, gates and scorers can be tested without network. Offline scores mean nothing."""
    u = messages[-1]["content"]
    tables = re.findall(r"TABLE (\w+)", u) or ["t"]
    cols = re.findall(r"^- (\w+) ", u, re.M)
    col = cols[0] if cols else "category"
    if tag == "plan":
        return json.dumps({"steps": [{"question": f"distribution of {col}",
                                      "sql": f"SELECT {col}, COUNT(*) AS n FROM {tables[0]} GROUP BY 1 ORDER BY n DESC LIMIT 5"}]})
    if tag == "evaluate":
        return json.dumps({"sufficient": True, "new_steps": []})
    if tag in ("write", "rag", "react_final"):
        nums = re.findall(r"\b\d+\b", u.split("RESULTS", 1)[-1])[:1] or ["1"]
        return json.dumps({"insights": [{"text": f"The most frequent {col} value accounts for {nums[0]} rows", "evidence": ["q1"]}],
                           "summary": f"The {col} distribution is skewed."})
    if tag == "react":
        if "OBSERVATION" in u:
            return json.dumps({"action": "final"})
        return json.dumps({"action": "sql", "sql": f"SELECT COUNT(*) AS n FROM {tables[0]}"})
    if tag == "sqlfix":
        return json.dumps({"sql": f"SELECT COUNT(*) AS n FROM {tables[0]}"})
    if tag == "faith":
        return "<rating>8</rating>"
    if tag == "judge":
        return "<rating>5</rating>"
    if tag.startswith("tat"):
        nums = re.findall(r"-?\d[\d,]*\.?\d*", u.split("QUESTION", 1)[0])
        v = nums[0].replace(",", "") if nums else "0"
        return json.dumps({"answer": v, "scale": "", "expression": v, "evidence": [v]})
    return "{}"


def default_offline() -> bool:
    return os.environ.get("BENCH_OFFLINE", "").lower() in ("1", "true", "yes")
