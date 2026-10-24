"""Proof-carrying receipts: POST /verify re-executes every claim's SQL against the live backend.

There is no cached or hardcoded verdict. Each call:
1. rebuilds the claim's SQL from its metric/segment/window (app.checks.claims.metric_sql),
2. executes it now on the current backend (Zetaris JDBC or the DuckDB snapshot),
3. re-checks the cited row ids, compares the fresh value with the value printed in the memo,
4. appends one `verify` event per claim to logs/trace-<run_id>.jsonl, and
5. returns a receipt with status green | red | unverifiable and the backend badge.

A receipt is green only if the fresh value is within the Claim Gate tolerance AND every cited row
still exists and matches. Anything else is red. Claims without a metric (e.g. narrative) are
`unverifiable`, never green.
"""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from .adapters.zetaris import badge
from .checks.claims import check_claim, metric_sql
from .config import ROOT


def _hash(sql: str, params: list) -> str:
    return hashlib.sha256(json.dumps([sql, params], default=str).encode()).hexdigest()[:16]


def verify_claim(db, claim: dict) -> dict:
    t0 = time.time()
    base = {"claim_id": claim.get("id"), "memo_value": claim.get("value"), "backend": badge(db),
            "backend_name": getattr(db, "name", type(db).__name__)}
    if not claim.get("metric"):
        return {**base, "status": "unverifiable", "reasons": ["claim has no metric/SQL to re-execute"],
                "sql": None, "params": None, "db_value": None}
    try:
        if str(claim["metric"]).startswith("olist."):
            from .olist import metrics as om
            sql, params = om.metric_sql(claim["metric"], claim["params"])
            chk = om.check(db, claim)
        else:
            sql, params = metric_sql(claim["metric"], claim.get("segment") or {}, claim["window"])
            chk = check_claim(db, claim)  # executes metric SQL + cited-row SQL now
    except Exception as e:  # backend down / bad claim -> red with reason, never green
        return {**base, "status": "red", "reasons": [f"{type(e).__name__}: {e}"], "sql": None, "params": None,
                "db_value": None, "elapsed_ms": round((time.time() - t0) * 1000, 1)}
    return {**base, "status": "green" if chk["passed"] else "red", "reasons": chk["reasons"],
            "sql": sql, "params": params, "sql_sha": _hash(sql, params), "db_value": chk["db_value"],
            "executed_at": round(time.time(), 3), "elapsed_ms": round((time.time() - t0) * 1000, 1)}


def _log(trace_path: Path, run_id: str, rec: dict) -> None:
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_id = None
    if trace_path.exists():
        for line in trace_path.read_text().splitlines()[:1]:
            trace_id = json.loads(line).get("trace_id")
    ev = {"ts": round(time.time(), 3), "run_id": run_id, "trace_id": trace_id, "agent": "verifier",
          "event": "verify", "data": rec}
    with trace_path.open("a") as f:
        f.write(json.dumps(ev, default=str) + "\n")


def verify_claims(db, claims: list[dict], run_id: str | None = None, log_dir: Path | None = None) -> dict:
    receipts = [verify_claim(db, c) for c in claims]
    if run_id:
        tp = (log_dir or ROOT / "logs") / f"trace-{run_id}.jsonl"
        for r in receipts:
            _log(tp, run_id, r)
    st = [r["status"] for r in receipts]
    return {"run_id": run_id, "backend": badge(db), "receipts": receipts,
            "summary": {"green": st.count("green"), "red": st.count("red"), "unverifiable": st.count("unverifiable")},
            "all_green": bool(st) and all(s == "green" for s in st)}
