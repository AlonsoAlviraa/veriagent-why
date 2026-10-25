"""V7 priority 1: POST /verify always re-executes the claim SQL; a mutated row must turn the receipt red."""
import json, shutil, subprocess, sys
from pathlib import Path
from fastapi.testclient import TestClient
from app.api import app
from app.config import log_dir
from app.adapters.zetaris import SnapshotBackend, VIEWS, badge, schema, SampleBackend

ROOT = Path(__file__).parents[1]
C = TestClient(app)
INP = json.loads((ROOT / "input_examples" / "example_1.json").read_text())["input"]


def _run(rid="verify-test"):
    r = C.post("/run", json={"run_id": rid, "input": INP}).json()["output"]["result"]
    assert r["claims"], "example must produce gate-approved claims"
    return rid, r


def _snapshot(tmp_path):
    out = tmp_path / "snap.duckdb"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_data.py"), "--out", str(out)], check=True, capture_output=True)
    return out


def test_verify_endpoint_reexecutes_and_logs(tmp_path):
    rid, r = _run()
    v = C.post("/verify", json={"run_id": rid}).json()
    assert v["backend"] == "snapshot" and v["all_green"]
    assert len(v["receipts"]) == len(r["claims"])
    for rc in v["receipts"]:
        assert rc["sql"].startswith("SELECT") and rc["db_value"] is not None and rc["executed_at"]
    ev = [json.loads(l) for l in (log_dir() / f"trace-{rid}.jsonl").read_text().splitlines()]
    ver = [e for e in ev if e["event"] == "verify"]
    assert len(ver) == len(r["claims"]) and all(e["agent"] == "verifier" for e in ver)
    v2 = C.post("/verify", json={"run_id": rid}).json()  # each call re-executes and logs again
    assert sum(1 for l in (log_dir() / f"trace-{rid}.jsonl").read_text().splitlines() if '"verify"' in l) == 2 * len(r["claims"])
    assert v2["receipts"][0]["executed_at"] >= v["receipts"][0]["executed_at"]


def test_mutated_row_turns_receipt_red(tmp_path):
    _, r = _run("verify-mut")
    snap = _snapshot(tmp_path)
    claims = r["claims"]
    from app.verify import verify_claims
    db = SnapshotBackend(snap)
    before = verify_claims(db, claims)
    assert before["all_green"], before
    db.con.close()
    # mutate: flip on_time for every row cited by the first claim (a real data change, not a flag)
    import duckdb
    con = duckdb.connect(str(snap))
    ids = claims[0]["row_ids"]
    con.execute(f"UPDATE t_logistics SET on_time = NOT on_time WHERE shipment_id IN ({','.join('?' * len(ids))})", ids)
    con.close()
    after = verify_claims(SnapshotBackend(snap), claims)
    rc = after["receipts"][0]
    assert rc["status"] == "red" and not after["all_green"]
    assert any("!= db" in x for x in rc["reasons"])


def test_deleted_row_turns_red_and_no_metric_is_unverifiable(tmp_path):
    _, r = _run("verify-del")
    snap = _snapshot(tmp_path)
    import duckdb
    con = duckdb.connect(str(snap))
    con.execute("DELETE FROM t_logistics WHERE shipment_id = ?", [r["claims"][0]["row_ids"][0]])
    con.close()
    from app.verify import verify_claims
    out = verify_claims(SnapshotBackend(snap), [r["claims"][0], {"id": "narrative", "text": "x"}])
    assert [x["status"] for x in out["receipts"]] == ["red", "unverifiable"]
    assert any("not found" in x for x in out["receipts"][0]["reasons"])


def test_backend_error_is_red_never_green():
    class Down:
        name = "down"
        def query(self, *a, **k):
            raise ConnectionError("unreachable")
    from app.verify import verify_claims
    out = verify_claims(Down(), [{"id": "c1", "metric": "on_time_rate", "segment": {}, "window": ["2026-01-01", "2026-01-31"], "value": 90, "row_ids": ["x"]}])
    assert out["receipts"][0]["status"] == "red" and out["backend"] == "snapshot"


def test_snapshot_schema_matches_demo_views(tmp_path):
    snap = _snapshot(tmp_path)
    s = schema(SnapshotBackend(snap))
    assert set(s) == set(VIEWS) and all(s[v] for v in VIEWS)
    assert schema(SampleBackend()) == s
    assert badge(SnapshotBackend(snap)) == "snapshot"


def test_verify_bad_request():
    assert C.post("/verify", json={}).status_code == 400
    assert C.post("/verify", json={"run_id": "does-not-exist"}).status_code == 404
