"""Nightshift-compatible local SIMULATOR (app/nightshift_sim.py). No network: the NVIDIA upstream is a local fake."""
import json, threading, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from app import nightshift_sim as sim

SEEN = []


class FakeNvidia(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append({"auth": self.headers.get("Authorization"), "body": body})
        out = json.dumps({"id": "x", "object": "chat.completion", "model": body["model"],
                          "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 3, "completion_tokens": 1}}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)


def _serve(srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture()
def stack(tmp_path, monkeypatch):
    up = ThreadingHTTPServer(("127.0.0.1", 0), FakeNvidia)
    monkeypatch.setenv("NVIDIA_BASE_URL", _serve(up) + "/v1")
    monkeypatch.setenv("NVIDIA_API_KEY", "upstream-test-key")
    monkeypatch.setenv("SIM_RPM", "6000")
    monkeypatch.delenv("SIM_UPSTREAM", raising=False)
    tf = tmp_path / "sim.token"
    monkeypatch.setenv("NIGHTSHIFT_SIM_TOKEN_FILE", str(tf))
    srv = sim.make_server(port=0)
    base = _serve(srv)
    yield base, tf
    srv.shutdown(); up.shutdown()


def _req(url, token=None, body=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h)
    with urllib.request.urlopen(r, timeout=10) as resp:
        return resp.status, dict(resp.headers), json.load(resp)


def test_token_file_created_private(stack):
    _, tf = stack
    assert tf.exists() and (__import__("os").name == "nt" or (tf.stat().st_mode & 0o077) == 0) and len(tf.read_text(encoding="utf-8")) >= 32


def test_rejects_missing_or_wrong_token(stack):
    base, _ = stack
    for tok in (None, "wrong"):
        with pytest.raises(urllib.error.HTTPError) as e:
            _req(base + "/v1/models", tok)
        assert e.value.code == 401


def test_chat_forwards_and_is_labelled_as_simulator(stack):
    base, tf = stack
    SEEN.clear()
    code, headers, out = _req(base + "/v1/chat/completions", tf.read_text(encoding="utf-8"),
                              {"model": "meterless/fast", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5})
    assert code == 200 and out["choices"][0]["message"]["content"] == "pong"
    assert "not Meterless Nightshift" in headers["x-simulator"]
    assert out["system_fingerprint"] == "nightshift-simulator" and out["simulator"]["upstream"] == "nvidia"
    assert SEEN[0]["auth"] == "Bearer upstream-test-key"  # upstream key used upstream only
    assert "lightning" in SEEN[0]["body"]["model"]  # routing mode mapped to a real model
    assert SEEN[0]["body"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_app_client_talks_to_simulator(stack, monkeypatch):
    base, tf = stack
    from app import llm
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("LLM_PROVIDER", "nightshift")
    monkeypatch.setenv("NIGHTSHIFT_BASE_URL", base + "/v1")
    monkeypatch.delenv("NIGHTSHIFT_API_KEY", raising=False)
    monkeypatch.setenv("NIGHTSHIFT_API_KEY_FILE", str(tf))
    monkeypatch.setenv("NIGHTSHIFT_PIN_CHECK", "off"); monkeypatch.setenv("NIGHTSHIFT_PIN_ENFORCE", "off")  # simulator is not Nightshift
    r = llm.complete([{"role": "user", "content": "ping"}], "s2", 5)
    assert r["content"] == "pong"


def test_nebius_upstream_refused_by_budget_guard(stack, monkeypatch, tmp_path):
    base, tf = stack
    monkeypatch.setenv("SIM_UPSTREAM", "nebius")
    monkeypatch.setenv("NEBIUS_API_KEY", "not-used-call-is-refused-before-network")
    monkeypatch.setenv("NEBIUS_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("NEBIUS_BUDGET_USD", "0")
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(base + "/v1/chat/completions", tf.read_text(encoding="utf-8"), {"messages": [{"role": "user", "content": "hi"}]})
    assert e.value.code == 402


def test_loopback_only():
    with pytest.raises(ValueError):
        sim.make_server(host="0.0.0.0", port=0, token="t")
