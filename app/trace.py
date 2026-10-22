"""JSONL trace logger: one JSON object per line in logs/trace-<run_id>.jsonl."""
from __future__ import annotations
import json, time, uuid
from pathlib import Path
from .config import ROOT, log_dir

SECRET_KEYS = {"key", "token", "secret", "password", "authorization", "api_key", "access_token", "bearer"}


def _clean(obj):
    if isinstance(obj, dict):
        return {k: ("[redacted]" if (k.lower() in SECRET_KEYS or k.lower().endswith(("_key", "_secret", "_password"))) else _clean(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _default_dir() -> Path:
    return log_dir()


class Tracer:
    def __init__(self, run_id: str, log_dir: Path | None = None):  # noqa: shadowing is local
        self.run_id, self.trace_id = run_id, uuid.uuid4().hex[:16]
        d = log_dir or _default_dir()
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"trace-{run_id}.jsonl"
        self.path.write_text("")
        self.events: list[dict] = []

    def log(self, agent: str, event: str, **data) -> None:
        rec = {"ts": round(time.time(), 3), "run_id": self.run_id, "trace_id": self.trace_id,
               "agent": agent, "event": event, "data": _clean(data)}
        self.events.append(rec)
        with self.path.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
