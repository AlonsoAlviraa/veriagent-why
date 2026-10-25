"""Embedder, hybrid fusion, Agentic Retriever caps / fallback / whitelist. Offline: HTTP is mocked."""
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import pytest
from app import embeddings
from app.retrieval import hybrid
from app.retrieval.agentic import AgenticRetriever, ToolError, CAPS
from app.adapters.zetaris import SampleBackend
from app.agents.core import Retriever, LLMCtx
from app.memory import HMem

INP = json.loads((Path(__file__).parents[1] / "input_examples" / "example_1.json").read_text(encoding="utf-8"))["input"]


def q():
    from app.pipeline import parse_question
    return parse_question(INP)


def test_hash_embedder_deterministic_unit_and_matches_vendored_contract():
    a, b = embeddings.hash_embed("late delivery CarrierB"), embeddings.hash_embed("late delivery CarrierB")
    assert a == b and len(a) == 64 and abs(sum(x * x for x in a) - 1) < 1e-9
    assert embeddings.backend() == "hash"  # sample mode: offline
    assert embeddings.cosine(a, [0.0] * 10) == 0.0  # mismatched dims never compare


def serve_embed(log):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            log.append({"path": self.path, "auth": self.headers.get("Authorization", "").startswith("Bearer "), **body})
            data = [{"index": i, "embedding": [float(len(t) % 7 + 1), 1.0, 0.0]} for i, t in enumerate(body["input"])]
            out = json.dumps({"data": data, "usage": {"total_tokens": 3}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
        def log_message(self, *a): pass
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_nvidia_embedder_mocked_http_input_type_and_disk_cache(monkeypatch, tmp_path):
    log = []
    s = serve_embed(log)
    monkeypatch.setenv("SAMPLE_MODE", "false"); monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-not-a-key"); monkeypatch.setenv("EMBED_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_BASE_URL", f"http://127.0.0.1:{s.server_port}/v1"); monkeypatch.setenv("MODEL_MIN_INTERVAL_S", "0")
    monkeypatch.setattr(embeddings, "CACHE", tmp_path)
    assert embeddings.backend() == "nvidia" and embeddings.model_name() == "nvidia/nemotron-3-embed-1b"
    v = embeddings.embed(["alpha", "beta gamma"], "passage")
    assert len(v) == 2 and abs(sum(x * x for x in v[0]) - 1) < 1e-9
    assert log[0]["path"] == "/v1/embeddings" and log[0]["input_type"] == "passage" and log[0]["auth"]
    embeddings.embed(["alpha", "beta gamma"], "passage")  # cached: no new request
    assert len(log) == 1 and len(list(tmp_path.iterdir())) == 2
    embeddings.embed(["alpha"], "query")  # queries are not cached
    assert log[-1]["input_type"] == "query" and len(log) == 2
    s.shutdown()


def test_rrf_fusion_math_and_ids_kept():
    f = hybrid.rrf([["a", "b", "c"], ["c", "a"]], k=60)
    assert f["a"] == pytest.approx(1 / 61 + 1 / 62) and f["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert max(f, key=f.get) == "a"
    rows = [{"ticket_id": "T1", "text": "parcel late, delayed delivery"}, {"ticket_id": "T2", "text": "invoice question"},
            {"ticket_id": "T3", "text": "delivery missed again late"}]
    hits, meta = hybrid.search(rows, "late delivery", "ticket_id")
    assert {h["ticket_id"] for h in hits[:2]} == {"T1", "T3"} and all("rrf" in h for h in hits) and meta["dense"] == "ok"


def test_hybrid_falls_back_to_bm25_when_embedder_fails(monkeypatch):
    monkeypatch.setattr(embeddings, "embed", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    hits, meta = hybrid.search([{"id": 1, "text": "late"}, {"id": 2, "text": "x"}], "late", "id")
    assert [h["id"] for h in hits] == [1] and meta["dense"].startswith("failed")


def agent():
    db = SampleBackend()
    return AgenticRetriever(db, Retriever(db)), db


def test_tool_whitelist_rejects_unknown_tools_bad_values_and_sql():
    a, _ = agent()
    with pytest.raises(ToolError):
        a.validate("raw_sql", {"sql": "DROP TABLE v_orders"}, q())
    with pytest.raises(ToolError):
        a.validate("segment_stats", {"dims": ["carrier; DROP"]}, q())
    with pytest.raises(ToolError):
        a.validate("drill_down", {"carrier": "X' OR 1=1 --"}, q())
    t = a.validate("text_search", {"query": "late'; DELETE FROM v_tickets"}, q())
    assert "'" not in t["query"] and ";" not in t["query"]
    d = a.validate("drill_down", {"carrier": "CarrierB", "date_from": "1999-01-01"}, q())
    assert d["date_from"] == str(q()["period"][0])  # clipped into the period


class FakeCtx(LLMCtx):
    def __init__(self, decisions):
        super().__init__(True); self.decisions = list(decisions); self.n = 0
    def attempt(self, agent, fn, *a):
        self.n += 1
        d = self.decisions.pop(0) if self.decisions else {"sufficient": False, "tool": "drill_down", "args": {"carrier": "CarrierB"}}
        if d == "fail":
            self.calls.append({"agent": agent, "ok": False}); return None
        self.calls.append({"agent": agent, "ok": True, "usage": {"total_tokens": 100}}); return d


HYPS = [{"id": "H_carrier", "type": "segment", "dims": ["carrier"], "text": "carrier"},
        {"id": "H_region", "type": "segment", "dims": ["region"], "text": "region"},
        {"id": "H_promo", "type": "promotion", "dims": [], "text": "promo"},
        {"id": "H_seasonal", "type": "seasonal", "dims": [], "text": "seasonal"}]


def test_agent_loop_caps_steps_per_hypothesis_and_round():
    a, _ = agent()
    ctx = FakeCtx([])  # model never says sufficient
    events = []
    a.log = lambda e, **d: events.append((e, d))
    a.retrieve(HYPS, q(), HMem(None), ctx)
    assert ctx.n <= CAPS["model_calls_per_round"]
    assert ctx.n == min(len(HYPS) * CAPS["model_steps_per_hyp"], CAPS["model_calls_per_round"])
    assert any(e == "tool_call" and d["source"] == "model" and d["tool"] == "drill_down" for e, d in events)


def test_agent_sufficient_stops_and_invalid_tool_is_rejected_and_traced():
    a, _ = agent()
    ev = []
    a.log = lambda e, **d: ev.append((e, d))
    ctx = FakeCtx([{"sufficient": False, "tool": "raw_sql", "args": {}}, {"sufficient": True, "tool": None}] + [{"sufficient": True}] * 5)
    a.retrieve(HYPS[:2], q(), HMem(None), ctx)
    assert any(e == "tool_rejected" for e, _ in ev) and ctx.n == 3


def test_model_failure_falls_back_to_deterministic_policy_same_as_sample():
    a, _ = agent()
    base = agent()[0].retrieve(HYPS, q(), HMem(None), None)
    got = a.retrieve(HYPS, q(), HMem(None), FakeCtx(["fail"] * 10))
    assert [c["text"] for c in got] == [c["text"] for c in base]
    assert a.stats["fallback_steps"] == len(HYPS)


def test_every_tool_call_is_an_hmem_retrieval_node():
    a, _ = agent()
    mem = HMem(None)
    for h in HYPS:
        mem.add_node(h["id"], "hypothesis", text=h["text"])
    a.retrieve(HYPS, q(), mem, None)
    r = [n for n in mem.nodes.values() if n["kind"] == "retrieval"]
    assert len(r) == a.stats["tool_calls"] and len(mem.edges_to("H_carrier", "retrieved_for")) == 1


def test_sample_pipeline_uses_agentic_retriever_and_reports_embedder():
    from app.pipeline import run
    res = run(INP, "test-agentic")
    r = res["output"]["result"]["retrieval"]
    assert r["mode"] == "agentic" and r["embed_backend"] == "hash" and r["stats"]["tool_calls"] > 0
    log = (Path(__file__).parents[1] / res["log_file"]).read_text(encoding="utf-8")
    assert '"tool_call"' in log
