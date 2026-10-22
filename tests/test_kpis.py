from app.kpis import detect, KpiLens
from app.adapters.zetaris import SampleBackend
from app.pipeline import run


def test_detect():
    assert detect("Why did on-time delivery drop?") == "on_time_rate"
    assert detect("Why did the return rate rise last week?") == "return_rate"
    assert detect("Why did revenue fall?") is None


def test_return_lens_matches_direct_sql():
    db = SampleBackend()
    lens = KpiLens(db, "return_rate")
    v = lens.query("SELECT AVG(CASE WHEN on_time THEN 0.0 ELSE 1 END) r FROM v_logistics WHERE ship_date BETWEEN ? AND ?", ["2026-10-01", "2026-10-14"])[0]["r"]
    d = db.query("SELECT AVG(CASE WHEN order_id IN (SELECT order_id FROM v_returns) THEN 1.0 ELSE 0 END) r FROM v_orders WHERE order_date BETWEEN ? AND ?", ["2026-10-01", "2026-10-14"])[0]["r"]
    assert abs(v - d) < 1e-9


def test_return_rate_on_demo_does_not_overclaim():
    r = run({"query": "return rate", "kpi": "return_rate", "baseline": ["2026-09-15", "2026-09-30"], "period": ["2026-10-01", "2026-10-14"]}, "t-ret")
    assert r["status"] == "partial" and r["output"]["result"]["confidence"]["confidence"] <= 40
