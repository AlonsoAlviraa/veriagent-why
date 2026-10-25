"""Live-provider code path against a local mock OpenAI-compatible server (no network, no key)."""
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import pytest

INP = json.loads((Path(__file__).parents[1] / "input_examples" / "example_1.json").read_text(encoding="utf-8"))["input"]


def serve(reply):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            txt = reply(body["messages"][0]["content"])
            out = json.dumps({"choices": [{"message": {"content": txt}}], "usage": {"total_tokens": 1}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
        def log_message(self, *a): pass
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def good(sys):
    if "retrieval agent" in sys: return '{"sufficient": false, "tool": "drill_down", "args": {"carrier": "CarrierB", "region": "North"}, "why": "check cell"}'
    if "plan" in sys: return '{"hypotheses": ["H_carrier", "H_region", "H_promo"]}'
    if "relevant" in sys: return '{"score": 0.9}'
    if "verify" in sys: return '{"verdict": "supports"}'
    if "label" in sys: return '{"label": "carrier_sla_breach"}'
    return "On-time delivery fell to 44.2% for CarrierB in North, against 93.0% in the baseline."


@pytest.fixture
def live(monkeypatch):
    def setup(reply):
        s = serve(reply)
        # loopback mock must never go through an HTTP(S)_PROXY (offline/sandboxed CI sets a dead proxy)
        for k in ("NO_PROXY", "no_proxy"):
            monkeypatch.setenv(k, "127.0.0.1,localhost")
        monkeypatch.setenv("SAMPLE_MODE", "false"); monkeypatch.setenv("LLM_PROVIDER", "nightshift")
        monkeypatch.setenv("NIGHTSHIFT_PIN_CHECK", "off"); monkeypatch.setenv("NIGHTSHIFT_PIN_ENFORCE", "off")  # mock has no meterless block
        monkeypatch.setenv("NIGHTSHIFT_BASE_URL", f"http://127.0.0.1:{s.server_port}/v1")
        return s
    return setup


def test_live_path_uses_model_and_gate_checks_narrative(live):
    live(good)
    from app.pipeline import run
    r = run(INP, "test-live")["output"]["result"]
    assert r["model_calls"] and all(c["ok"] for c in r["model_calls"])
    assert r["narrative"] and "narrative" not in r["blocked_claims"]


def test_hallucinated_number_is_blocked(live):
    live(lambda sys: good(sys) if "summary" not in sys else "On-time delivery fell by 87.3% everywhere.")
    from app.pipeline import run
    r = run(INP, "test-halluc")["output"]["result"]
    assert r["narrative"] is None and "narrative" in r["blocked_claims"]


def test_empty_model_response_falls_back(live):
    live(lambda sys: "")
    from app.pipeline import run
    out = run(INP, "test-empty")
    r = out["output"]["result"]
    assert r["analysis"]["top_cause_label"] == "carrier_sla_breach"
    assert any(not c["ok"] and "empty" in c["error"] for c in r["model_calls"])
