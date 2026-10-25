"""Nightshift-compatible LOCAL SIMULATOR. This is NOT Meterless Nightshift.

Meterless Nightshift (the real product) was not available to us during the build window, so this
module stands in for it with the same client-facing contract the app already uses
(`LLM_PROVIDER=nightshift`): an OpenAI-compatible server on http://127.0.0.1:8088/v1 with a bearer
token. It does no Meterless metering or routing of its own: it forwards each chat completion to

- `SIM_UPSTREAM=nvidia` (default): NVIDIA build free endpoint (NVIDIA_API_KEY), paced to at most
  40 requests/minute shared by this process (SIM_RPM, default 40);
- `SIM_UPSTREAM=nebius`: Nebius Token Factory through the hard, file-locked spend guard in
  bench/nebius.py (NEBIUS_BUDGET_USD, ledger ~/.veriagent/nebius_spend.json). A refused call is
  answered with HTTP 402 and is never retried elsewhere.

Every response is labelled: header `x-simulator: nightshift-simulator (not Meterless Nightshift)`,
`system_fingerprint = "nightshift-simulator"` and a `simulator` object naming the real upstream.

Auth: the bearer token is read from NIGHTSHIFT_SIM_TOKEN_FILE (default ~/.veriagent/nightshift-sim.token).
If the file does not exist a random token is created with mode 0600. The token is never printed;
point the client at the same file with NIGHTSHIFT_API_KEY_FILE.

    python -m app.nightshift_sim            # serves 127.0.0.1:8088
    LLM_PROVIDER=nightshift NIGHTSHIFT_API_KEY_FILE=~/.veriagent/nightshift-sim.token python run.py --input ...
"""
from __future__ import annotations
import hmac, json, os, secrets, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LABEL = "nightshift-simulator (not Meterless Nightshift)"
DEFAULT_TOKEN_FILE = Path.home() / ".veriagent" / "nightshift-sim.token"
_PACE = threading.Lock()
_LAST = [0.0]


def token_file() -> Path:
    return Path(os.environ.get("NIGHTSHIFT_SIM_TOKEN_FILE") or DEFAULT_TOKEN_FILE).expanduser()


def load_token(path: Path | None = None) -> str:
    p = path or token_file()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    t = p.read_text(encoding="utf-8").strip()
    if not t:
        raise RuntimeError(f"empty token file {p}")
    return t


def upstream() -> str:
    u = (os.environ.get("SIM_UPSTREAM") or "nvidia").lower()
    if u not in ("nvidia", "nebius"):
        raise ValueError(f"SIM_UPSTREAM must be nvidia or nebius, got {u!r}")
    return u


def map_model(requested: str | None, up: str) -> str:
    """Nightshift model ids are routing modes (meterless/auto, .../fast). Map them to a real upstream model."""
    r = (requested or "meterless/auto").strip()
    if up == "nebius":
        from bench import nebius
        return r if r in nebius.PRICES else (os.environ.get("NEBIUS_MODEL") or nebius.DEFAULT_MODEL)
    if r.startswith("nvidia/"):
        return r
    fast = any(k in r.lower() for k in ("fast", "s1", "lightning"))
    return os.environ.get("FAST_MODEL" if fast else "REASONING_MODEL") or (
        "nvidia/nemotron-3.5-lightning-30b-a3b" if fast else "nvidia/nemotron-3.5-super-vl-120b-a12b")


def _pace() -> None:
    gap = 60.0 / float(os.environ.get("SIM_RPM") or 40)
    with _PACE:
        wait = _LAST[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _LAST[0] = time.time()


def forward(body: dict) -> tuple[int, dict]:
    up = upstream()
    model = map_model(body.get("model"), up)
    msgs = body.get("messages") or []
    max_tokens = int(body.get("max_tokens") or 1024)
    if up == "nebius":
        from bench import nebius
        try:
            r = nebius.complete(msgs, model, max_tokens, float(os.environ.get("MODEL_TIMEOUT_S") or 180))
        except nebius.NebiusBudgetExceeded as e:
            return 402, {"error": {"type": "budget_exceeded", "message": str(e)}}
        out = {"id": f"sim-{time.time_ns()}", "object": "chat.completion", "created": int(time.time()), "model": model,
               "choices": [{"index": 0, "message": {"role": "assistant", "content": r["content"]}, "finish_reason": r.get("finish_reason")}],
               "usage": r.get("usage")}
    else:
        key = os.environ.get("NVIDIA_API_KEY")
        if not key:
            return 503, {"error": {"type": "upstream_unconfigured", "message": "NVIDIA_API_KEY not set"}}
        fwd = {k: v for k, v in body.items() if k in ("messages", "max_tokens", "temperature", "top_p", "response_format", "stop", "chat_template_kwargs")}
        fwd["model"] = model
        fwd.setdefault("chat_template_kwargs", {"enable_thinking": False})
        base = (os.environ.get("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1").rstrip("/")
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(fwd).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        _pace()
        try:
            with urllib.request.urlopen(req, timeout=float(os.environ.get("MODEL_TIMEOUT_S") or 180)) as r:
                out = json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, {"error": {"type": "upstream_http_error", "message": f"NVIDIA upstream returned HTTP {e.code}"}}
    out["system_fingerprint"] = "nightshift-simulator"
    out["simulator"] = {"label": LABEL, "upstream": up, "upstream_model": model, "requested_model": body.get("model")}
    return 200, out


class Handler(BaseHTTPRequestHandler):
    token = ""
    server_version = "nightshift-simulator"

    def log_message(self, fmt, *args):  # one line per request on stderr, never headers (no token leaks)
        sys.stderr.write(f"[{LABEL}] {self.command} {self.path.split('?')[0]} -> {args[1] if len(args) > 1 else ''}\n")

    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("x-simulator", LABEL)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self) -> bool:
        h = self.headers.get("Authorization") or ""
        ok = h.startswith("Bearer ") and hmac.compare_digest(h[7:].strip().encode(), self.token.encode())
        if not ok:
            self._send(401, {"error": {"type": "unauthorized", "message": "missing or wrong bearer token"}})
        return ok

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            return self._send(200, {"ok": True, "simulator": LABEL, "upstream": upstream()})
        if not self._authed():
            return
        if self.path.rstrip("/") == "/v1/models":
            return self._send(200, {"object": "list", "simulator": LABEL, "data": [
                {"id": m, "object": "model", "owned_by": "nightshift-simulator"} for m in ("meterless/auto", "meterless/fast")]})
        self._send(404, {"error": {"type": "not_found"}})

    def do_POST(self):
        if not self._authed():
            return
        if self.path.rstrip("/") != "/v1/chat/completions":
            return self._send(404, {"error": {"type": "not_found"}})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if body.get("stream"):
                return self._send(400, {"error": {"type": "unsupported", "message": "stream=true is not supported by the simulator"}})
            code, out = forward(body)
        except Exception as e:
            code, out = 502, {"error": {"type": type(e).__name__, "message": str(e)[:200]}}
        self._send(code, out)


def make_server(host: str = "127.0.0.1", port: int = 8088, token: str | None = None) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the simulator binds to loopback only")
    h = type("H", (Handler,), {"token": token if token is not None else load_token()})
    return ThreadingHTTPServer((host, port), h)


def main() -> None:
    from .config import load_dotenv
    load_dotenv()
    port = int(os.environ.get("NIGHTSHIFT_SIM_PORT") or 8088)
    srv = make_server(port=port)
    print(f"{LABEL}: http://127.0.0.1:{port}/v1 -> upstream {upstream()} (token file {token_file()})", file=sys.stderr)
    srv.serve_forever()


if __name__ == "__main__":
    main()
