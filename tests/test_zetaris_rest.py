"""ZetarisBackend against a local mock of the documented REST shape (no live Zetaris)."""
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from app.adapters.zetaris import ZetarisBackend

SEEN = {}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        SEEN["path"], SEEN["auth"], SEEN["org"] = self.path, self.headers["Authorization"], self.headers["X-Org-ID"]
        SEEN["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        out = json.dumps({"columns": [{"name": "one"}], "data": [[1]]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass


def test_rest_shape_and_literal_escaping(monkeypatch):
    s = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
    monkeypatch.setenv("ZETARIS_REST_URL", f"http://127.0.0.1:{s.server_port}/api/v1.0")
    monkeypatch.setenv("ZETARIS_API_KEY", "test-not-a-secret"); monkeypatch.setenv("ZETARIS_ORG_ID", "org1")
    monkeypatch.setenv("ZETARIS_VIEW_PREFIX", "hack.")
    b = ZetarisBackend()
    assert b.query("SELECT 1 AS one FROM v_orders WHERE region = ?", ["O'Brien"]) == [{"one": 1}]
    assert SEEN["path"] == "/api/v1.0/sql-editor/sqls/run" and SEEN["org"] == "org1"
    assert SEEN["body"]["sql"] == "SELECT 1 AS one FROM hack.v_orders WHERE region = 'O''Brien'"
    assert SEEN["body"]["source"] == "SqlEditor"
