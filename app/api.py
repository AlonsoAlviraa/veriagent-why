"""FastAPI on :8000. POST /run (sync JSON), POST /runs (async, for the UI), GET /runs/{id}/trace,
GET /runs/{id}, GET /memo/{id}.md|.pdf, POST /runs/{id}/whatif (ESTIMATE),
POST /verify (re-executes every claim's SQL now; see app/verify.py). The UI is a separate app (app/ui.py)."""
from __future__ import annotations
import json, threading, time, uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from .pipeline import run
from .config import ROOT, log_dir

app = FastAPI(title="VeriAgent Why")
STATE: dict[str, dict] = {}


def _rid(run_id: str) -> str:
    if not run_id.replace("-", "").isalnum() or len(run_id) > 64:
        raise HTTPException(400, "invalid run id")
    return run_id


def _error(rid, e, t0):
    return {"run_id": rid, "status": "error", "error": {"type": "invalid_input", "message": str(e), "recoverable": True},
            "trace_id": None, "execution_time_seconds": round(time.time() - t0, 3)}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/run")
def run_endpoint(req: dict):
    rid = req.get("run_id") or uuid.uuid4().hex[:12]
    t0 = time.time()
    try:
        return run(req.get("input", {}), _rid(rid))
    except ValueError as e:
        return _error(rid, e, t0)


@app.post("/runs")
def start(req: dict):
    rid = _rid(req.get("run_id") or uuid.uuid4().hex[:12])
    STATE[rid] = {"status": "running"}
    def work():
        t0 = time.time()
        try:
            STATE[rid] = run(req.get("input", {}), rid)
        except Exception as e:  # reported to the UI, never crashes the API
            STATE[rid] = _error(rid, e, t0)
    threading.Thread(target=work, daemon=True).start()
    return {"run_id": rid, "status": "running"}


@app.get("/runs/{run_id}/trace")
def trace(run_id: str, since: int = 0):
    p = log_dir() / f"trace-{_rid(run_id)}.jsonl"
    lines = p.read_text().splitlines() if p.exists() else []
    return {"status": STATE.get(run_id, {}).get("status", "unknown"), "events": [json.loads(l) for l in lines[since:]], "next": len(lines)}


@app.get("/runs/{run_id}")
def result(run_id: str):
    p = log_dir() / f"result-{_rid(run_id)}.json"
    if not p.exists():
        raise HTTPException(404, "not found")
    return json.loads(p.read_text())


@app.post("/runs/{run_id}/whatif")
def whatif_ep(run_id: str):
    from .adapters.zetaris import get_backend
    from .whatif import whatif
    r = result(run_id)
    from .kpis import KpiLens
    return whatif(KpiLens(get_backend(r["question"].get("dataset")), r["question"]["kpi"]), r)


@app.get("/memo/{run_id}.md", response_class=PlainTextResponse)
def memo(run_id: str):
    p = log_dir() / f"memo-{_rid(run_id)}.md"
    if not p.exists():
        raise HTTPException(404, "not found")
    return p.read_text()


@app.get("/memo/{run_id}.pdf")
def memo_pdf(run_id: str):
    p = log_dir() / f"memo-{_rid(run_id)}.pdf"
    if not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(p, media_type="application/pdf", filename=f"memo-{run_id}.pdf")


@app.get("/rows/{view}/{row_id}")
def row(view: str, row_id: str, dataset: str | None = None):
    """Claim click-through: the raw row behind a citation."""
    from .adapters.zetaris import get_backend
    keys = {"v_logistics": "shipment_id", "v_orders": "order_id", "v_tickets": "ticket_id", "v_returns": "return_id", "v_promotions": "promo_id"}
    if view not in keys:
        raise HTTPException(400, "unknown view")
    rows = get_backend(dataset).query(f"SELECT * FROM {view} WHERE {keys[view]} = ?", [row_id])
    if not rows:
        raise HTTPException(404, "not found")
    return json.loads(json.dumps(rows[0], default=str))


@app.post("/verify")
def verify_ep(req: dict):
    """Body: {"run_id": "..."} (verifies the stored memo's claims) or {"claims": [...]}.
    Always re-executes the SQL on the current backend and logs `verify` events to the run trace."""
    from .adapters.zetaris import get_backend
    from .verify import verify_claims
    rid = req.get("run_id")
    if rid:
        r = result(_rid(rid))
        claims, dataset = r.get("claims", []), r.get("question", {}).get("dataset")
    else:
        claims, dataset = req.get("claims"), req.get("dataset")
        if not isinstance(claims, list) or not claims:
            raise HTTPException(400, "provide run_id or a non-empty claims list")
    try:
        if dataset == "olist":
            from .olist.backend import olist_backend
            db = olist_backend()
        else:
            db = get_backend(dataset)
    except Exception as e:
        raise HTTPException(503, f"backend unavailable: {type(e).__name__}")
    return verify_claims(db, claims, run_id=rid, log_dir=LOGS)
