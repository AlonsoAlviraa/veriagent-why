"""Nightshift primary provider against an offline mock of the Meterless Runtime (no network, no key)."""
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import pytest

INP = json.loads((Path(__file__).parents[1] / "input_examples" / "example_1.json").read_text())["input"]
LIGHT, ULTRA = "nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia/nemotron-3-ultra-550b-a50b"


def mock(route, seen, status=200):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"body": b, "headers": {k.lower(): v for k, v in self.headers.items()}})
            sys = b["messages"][0]["content"]
            txt = ('{"hypotheses": ["H_carrier", "H_region", "H_promo"]}' if "plan" in sys else '{"score": 0.9}' if "relevant" in sys
                   else '{"verdict": "supports"}' if "verify" in sys else '{"label": "carrier_sla_breach"}' if "label" in sys
                   else "OK" if "OK" in sys else "On-time delivery fell to 44.2% for CarrierB in North, against 93.0% in the baseline.")
            out = {"choices": [{"message": {"content": txt}, "finish_reason": "stop"}], "usage": {"total_tokens": 3},
                   "meterless": {"request_id": f"chatcmpl-{len(seen)}", "requested_model": b["model"], "provider_model": b["model"],
                                 "routed_model": route(b), "app": self.headers.get("meterless-app"), "mode": "fast", "scope": "user"}}
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps(out).encode())
        def log_message(self, *a): pass
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def good_route(b):
    return LIGHT if b.get("chat_template_kwargs") else ULTRA


@pytest.fixture
def ns(monkeypatch, tmp_path):
    def setup(route=good_route):
        seen = []
        s = mock(route, seen)
        for k in ("NO_PROXY", "no_proxy"):
            monkeypatch.setenv(k, "127.0.0.1,localhost")
        monkeypatch.setenv("SAMPLE_MODE", "false"); monkeypatch.setenv("LLM_PROVIDER", "nightshift")
        monkeypatch.setenv("NIGHTSHIFT_BASE_URL", f"http://127.0.0.1:{s.server_port}/v1")
        monkeypatch.setenv("NIGHTSHIFT_API_KEY", "test-token-not-real")
        monkeypatch.delenv("LLM_FALLBACK", raising=False)
        from app import nightshift as NS
        monkeypatch.setenv("VA_LOG_DIR", str(tmp_path)); NS.set_run("t-ns", tmp_path)
        return seen, tmp_path
    return setup


def receipts(d, rid="t-ns"):
    return [json.loads(l) for l in (d / f"receipts-{rid}.jsonl").read_text().splitlines()]


def test_receipt_and_pins(ns):
    seen, d = ns()
    from app import llm
    r = llm.complete([{"role": "user", "content": "Reply OK"}], tier="s1", max_tokens=5000)
    assert r["routed_model"] == LIGHT and r["request_id"] == "chatcmpl-1"
    b = seen[0]["body"]
    assert b["chat_template_kwargs"] == {"enable_thinking": False} and b["max_tokens"] == 512  # reasoning off, bounded
    assert seen[0]["headers"]["meterless-app"] == "veriagent-why" and seen[0]["headers"]["meterless-scope"] == "user"
    rec = receipts(d)[0]
    assert rec["pin_ok"] and rec["routed_model"] == LIGHT and rec["requested_model"] == "meterless/fast" and not rec["fallback"]
    assert "test-token-not-real" not in (d / "receipts-t-ns.jsonl").read_text()


def test_mismatch_fails_loudly(ns):
    seen, d = ns(route=lambda b: "local-runtime/llama-3.2-3b-instruct")
    from app import llm, nightshift as NS
    with pytest.raises(NS.PinMismatch):
        llm.complete([{"role": "user", "content": "x"}], tier="s2")
    assert receipts(d)[0]["pin_ok"] is False


def test_pipeline_startup_check_blocks_run(ns):
    ns(route=lambda b: "nvidia/nemotron-3.5-super-120b")
    from app.pipeline import run
    from app.nightshift import PinMismatch
    with pytest.raises(PinMismatch):
        run(INP, "t-ns")


def test_pipeline_run_records_receipts(ns):
    seen, d = ns()
    from app.pipeline import run
    r = run(INP, "t-ns")["output"]["result"]
    recs = receipts(d)
    assert recs[0]["purpose"] == "pin_check" and {x["tier"] for x in recs[:2]} == {"s1", "s2"}
    assert all(x["pin_ok"] for x in recs) and len(recs) > 2
    ok = [c for c in r["model_calls"] if c["ok"]]
    assert ok and all(c["request_id"] for c in ok)


def test_bounded_prompt():
    from app.nightshift import bound_messages
    m, t = bound_messages([{"role": "user", "content": "a" * 50000}], limit=1000)
    assert t and len(m[0]["content"]) < 1100


def test_fallback_is_flagged(monkeypatch, tmp_path):
    for k in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(k, "127.0.0.1,localhost")
    seen = []; s = mock(lambda b: b["model"], seen)  # stands in for NVIDIA
    monkeypatch.setenv("SAMPLE_MODE", "false"); monkeypatch.setenv("LLM_PROVIDER", "nightshift")
    monkeypatch.setenv("NIGHTSHIFT_BASE_URL", "http://127.0.0.1:9/v1")  # closed port
    monkeypatch.setenv("NVIDIA_BASE_URL", f"http://127.0.0.1:{s.server_port}/v1"); monkeypatch.setenv("LLM_FALLBACK", "nvidia")
    from app import llm, nightshift as NS
    NS.set_run("t-fb", tmp_path)
    r = llm.complete([{"role": "user", "content": "Reply OK"}], tier="s1")
    assert r["provider"] == "nvidia" and r["fallback"]
    rec = receipts(tmp_path, "t-fb")[0]
    assert rec["fallback"] and rec["fallback_provider"] == "nvidia" and rec["pin_ok"] is None and "error" in rec["fallback_reason"]


def test_no_fallback_by_default(ns, monkeypatch):
    ns()
    monkeypatch.setenv("NIGHTSHIFT_BASE_URL", "http://127.0.0.1:9/v1")
    from app import llm
    with pytest.raises(Exception):
        llm.complete([{"role": "user", "content": "x"}], tier="s1")
