"""Web UI on a separate port (default 8501). Serves one static page and proxies /api/* to the API
(API_URL, default http://localhost:8000). The UI never runs the pipeline itself."""
from __future__ import annotations
import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from .config import ROOT

API = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
ui = FastAPI(title="VeriAgent Why UI")


@ui.get("/")
def index():
    return FileResponse(ROOT / "app" / "static" / "index.html")


@ui.api_route("/api/{path:path}", methods=["GET", "POST"])
async def proxy(path: str, request: Request):
    async with httpx.AsyncClient(timeout=600) as c:
        r = await c.request(request.method, f"{API}/{path}", params=request.query_params, content=await request.body(),
                            headers={"Content-Type": request.headers.get("content-type", "application/json")})
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))
