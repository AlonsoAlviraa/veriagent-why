import json, time
from pathlib import Path
from fastapi.testclient import TestClient
from app.api import app

C = TestClient(app)
INP = json.loads((Path(__file__).parents[1] / "input_examples" / "example_1.json").read_text())["input"]


def test_async_run_trace_result_whatif_pdf():
    rid = C.post("/runs", json={"run_id": "api-test", "input": INP}).json()["run_id"]
    for _ in range(100):
        if C.get(f"/runs/{rid}/trace").json()["status"] == "success":
            break
        time.sleep(0.1)
    r = C.get(f"/runs/{rid}").json()
    assert r["analysis"]["top_cause_label"] == "carrier_sla_breach"
    w = C.post(f"/runs/{rid}/whatif").json()
    assert w["label"] == "ESTIMATE" and w["estimated_on_time_rate_if_segment_at_baseline"] > w["observed_on_time_rate"]
    assert C.get(f"/memo/{rid}.pdf").content[:4] == b"%PDF"
    row = C.get(f"/rows/v_logistics/{r['claims'][0]['row_ids'][0]}").json()
    assert row["carrier"] == "CarrierB"


def test_bad_input_and_ids():
    assert C.post("/run", json={"input": {"query": "why"}}).json()["status"] == "error"
    assert C.get("/runs/..%2Fetc/trace").status_code in (400, 404)
    assert C.get("/rows/v_secret/x").status_code == 400
