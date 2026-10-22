"""Second federated source: serves v_tickets and v_promotions as JSON ({"rows": [...]}) from the local
snapshot, for the Zetaris REST tables created by zetaris_load.py. Keep it running during the demo.
Binds 0.0.0.0 so the Zetaris containers reach it via host.docker.internal. Read-only, GET only."""
from __future__ import annotations
import argparse, json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from _zetaris_common import ROOT

SERVED = ("v_tickets", "v_promotions")


def payload(snapshot, view):
    import duckdb
    con = duckdb.connect(str(snapshot), read_only=True)
    cur = con.execute(f"SELECT * FROM {view}")
    cols = [d[0] for d in cur.description]
    return {"rows": [{c: (str(x) if x is not None and not isinstance(x, (int, float, bool, str)) else x)
                      for c, x in zip(cols, r)} for r in cur.fetchall()]}


def make_handler(snapshot):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            v = self.path.strip("/").split("?")[0]
            if v not in SERVED:
                self.send_response(404); self.end_headers(); return
            body = json.dumps(payload(snapshot, v)).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    return H


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("VA_REST_PORT", "8765")))
    ap.add_argument("--snapshot", default=str(ROOT / "data" / "snapshot.duckdb"))
    a = ap.parse_args()
    print(f"serving {SERVED} on 0.0.0.0:{a.port} (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(a.snapshot)).serve_forever()
