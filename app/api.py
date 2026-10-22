"""FastAPI: POST /run -> JSON (docs/IO_CONTRACT.md). UI will live on a separate port."""
from __future__ import annotations
import time, uuid
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from .pipeline import run
from .config import ROOT

app = FastAPI(title="VeriAgent Why")


@app.post("/run")
def run_endpoint(req: dict):
    rid = req.get("run_id") or uuid.uuid4().hex[:12]
    t0 = time.time()
    try:
        return run(req.get("input", {}), rid)
    except ValueError as e:
        return {"run_id": rid, "status": "error", "error": {"type": "invalid_input", "message": str(e), "recoverable": True},
                "trace_id": None, "execution_time_seconds": round(time.time() - t0, 3)}


@app.get("/memo/{run_id}.md", response_class=PlainTextResponse)
def memo(run_id: str):
    if not run_id.replace("-", "").isalnum():
        return PlainTextResponse("invalid run id", status_code=400)
    p = ROOT / "logs" / f"memo-{run_id}.md"
    return p.read_text() if p.exists() else PlainTextResponse("not found", status_code=404)
