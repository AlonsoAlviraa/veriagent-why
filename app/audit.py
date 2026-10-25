"""Per-run audit trace for the main app: logs/<run_id>/audit.json next to a copy of the memo.
Built from the Tracer events (every agent step) and the final result: planner, SQL, evidence evaluation, requery,
cause analyst, writer, traceability check, verify-retry attempts (if any), confidence and the narrative. Long strings are
truncated (AUDIT_PROMPT_CHARS, default 2000); secrets are redacted with the same scanner as the bench traces."""
from __future__ import annotations
import json, os, shutil
from pathlib import Path

STAGES = [("planner", ("planner", "plan")), ("sql", ("sql", "s1", "retriev", "kpi")), ("evidence", ("evidence",)),
          ("requery", ("requery", "investigat", "markov")), ("cause_analyst", ("cause", "analyst")), ("writer", ("writer",)),
          ("claim_gate", ("gate",)), ("verify_retry", ("verif",)), ("observability", ("observab", "report")), ("orchestrator", ("orchestr",))]


def _stage(agent: str) -> str:
    a = (agent or "").lower()
    for name, keys in STAGES:
        if any(k in a for k in keys):
            return name
    return "other"


def _trunc(x, n):
    if isinstance(x, str):
        return x if len(x) <= n else x[:n] + f"... [truncated, {len(x)} chars]"
    if isinstance(x, dict):
        return {k: _trunc(v, n) for k, v in x.items()}
    if isinstance(x, list):
        return [_trunc(v, n) for v in x[:200]]
    return x


def build(events: list[dict], out: dict, run_id: str) -> dict:
    n = int(os.environ.get("AUDIT_PROMPT_CHARS", "2000"))
    flow = {name: [] for name, _ in STAGES} | {"other": []}
    for e in events:
        flow[_stage(e.get("agent"))].append({"ts": e.get("ts"), "agent": e.get("agent"), "event": e.get("event"), "data": _trunc(e.get("data"), n)})
    t = {"schema_version": "app-audit/1", "run_id": run_id, "question": _trunc(out.get("question"), n), "flow": flow,
         "claims": _trunc(out.get("claims"), n), "blocked_claims": out.get("blocked_claims"),
         "verify_retry_attempts": out.get("vr_attempts") or "not_run_in_app",
         "confidence": out.get("confidence"), "narrative": out.get("narrative"), "resolution": out.get("resolution"),
         "unresolved_reasons": out.get("unresolved_reasons"), "model_calls": out.get("model_calls"),
         "run_report": _trunc(out.get("run_report"), n)}
    from bench.audit_trace import secret_scan
    t, scan = secret_scan(t)
    t["secret_scan"] = scan
    return t


def write(log_dir: Path, events: list[dict], out: dict, run_id: str, memo_path: Path | None = None) -> Path:
    d = Path(log_dir) / run_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(build(events, out, run_id), indent=1, ensure_ascii=False, default=str))
    if memo_path and Path(memo_path).exists():
        shutil.copy(memo_path, d / "memo.md")
    return p
