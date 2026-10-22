from app.adapters.zetaris import SampleBackend
from app.checks.claims import check_claim, metric_value

DB = SampleBackend()
SEG = {"carrier": "CarrierB", "region": "North"}
WIN = ["2026-10-01", "2026-10-14"]


def good():
    v = metric_value(DB, "on_time_rate", SEG, WIN)
    ids = [r["shipment_id"] for r in DB.query("SELECT shipment_id FROM v_logistics WHERE carrier='CarrierB' AND region='North' AND ship_date BETWEEN '2026-10-01' AND '2026-10-14' LIMIT 3")]
    return {"id": "c", "metric": "on_time_rate", "segment": SEG, "window": WIN, "value": round(v, 2), "row_ids": ids}


def test_valid_claim_passes():
    assert check_claim(DB, good())["passed"]


def test_wrong_number_blocked():
    c = good(); c["value"] += 1.0
    assert not check_claim(DB, c)["passed"]


def test_within_tolerance_passes():
    c = good(); c["value"] += 0.4
    assert check_claim(DB, c)["passed"]


def test_missing_row_blocked():
    c = good(); c["row_ids"].append("S999999")
    assert not check_claim(DB, c)["passed"]


def test_row_from_other_segment_blocked():
    c = good()
    c["row_ids"].append(DB.query("SELECT shipment_id FROM v_logistics WHERE region='South' LIMIT 1")[0]["shipment_id"])
    assert not check_claim(DB, c)["passed"]


def test_no_rows_blocked():
    c = good(); c["row_ids"] = []
    assert not check_claim(DB, c)["passed"]
