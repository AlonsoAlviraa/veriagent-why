"""Olist demo logic on a tiny SYNTHETIC fixture with the Olist schema (CI has no Olist download).
The real-data run is scripts/olist_demo.py; these tests check the mechanics only."""
import datetime as dt, json, random
import duckdb, pytest
from app.olist import metrics as om
from app.olist.backend import OlistSnapshot
from app.olist.investigate import run_question, why_diff, sensitivity, render_memo
from app.olist.questions import QUESTIONS
from app.verify import verify_claims
from app.adapters.zetaris import render


def _fixture(path):
    rnd = random.Random(7)
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE ol_orders (order_id VARCHAR, customer_state VARCHAR, status VARCHAR, purchase_date DATE, delivered BOOLEAN, late BOOLEAN, delivery_days DOUBLE, handling_days DOUBLE, transit_days DOUBLE)")
    con.execute("CREATE TABLE ol_items (order_id VARCHAR, item_no INTEGER, product_id VARCHAR, seller_id VARCHAR, category VARCHAR, price DOUBLE, freight DOUBLE)")
    con.execute("CREATE TABLE ol_reviews (review_id VARCHAR, order_id VARCHAR, score INTEGER, created_date DATE)")
    con.execute("CREATE TABLE ol_sellers (seller_id VARCHAR, seller_state VARCHAR)")
    con.executemany("INSERT INTO ol_sellers VALUES (?,?)", [(f"s{i}", ["SP", "RJ", "MG"][i % 3]) for i in range(6)])
    d0 = dt.date(2017, 1, 1)
    O, I, R = [], [], []
    for i in range(3000):
        d = d0 + dt.timedelta(days=rnd.randrange(0, 600))
        hot = dt.date(2017, 11, 1) <= d <= dt.date(2017, 11, 30) or dt.date(2018, 2, 1) <= d <= dt.date(2018, 3, 31)
        late = rnd.random() < (0.3 if hot else 0.05)
        tr = rnd.uniform(5, 9) + (4 if hot else 0)
        st = ["SP", "RJ", "MG", "BA"][i % 4]
        oid = f"o{i:05d}"
        O.append([oid, st, "delivered", d, True, late, tr + 3, 3.0, tr])
        I.append([oid, 1, "p", f"s{i % 6}", "x", 100.0, rnd.uniform(5, 40)])
        if i % 10 == 0:
            I.append([oid, 2, "p", f"s{(i + 1) % 6}", "x", 50.0, 10.0])
        R.append([f"r{i}", oid, 1 if (late and rnd.random() < 0.6) else rnd.choice([2, 4, 5, 5, 5]), d])
    con.executemany("INSERT INTO ol_orders VALUES (?,?,?,?,?,?,?,?,?)", O)
    con.executemany("INSERT INTO ol_items VALUES (?,?,?,?,?,?,?)", I)
    con.executemany("INSERT INTO ol_reviews VALUES (?,?,?,?)", R)
    con.close()
    return path


@pytest.fixture(scope="module")
def _base(tmp_path_factory):
    return _fixture(tmp_path_factory.mktemp("olist") / "olist.duckdb")


@pytest.fixture
def db(_base, tmp_path):
    import shutil
    return OlistSnapshot(shutil.copy(_base, tmp_path / "olist.duckdb"), read_only=False)


def test_three_questions_green_and_trace(db, tmp_path):
    assert len(QUESTIONS) == 3
    for qid in QUESTIONS:
        r = run_question(qid, db, f"t-{qid}", tmp_path)
        v = verify_claims(db, r["claims"], run_id=f"t-{qid}", log_dir=tmp_path)
        assert v["all_green"], v["receipts"]
        ev = [json.loads(l) for l in (tmp_path / f"trace-t-{qid}.jsonl").read_text().splitlines()]
        kinds = [e["event"] for e in ev]
        assert "hypothesis_update" in kinds and kinds.count("verify") == len(r["claims"])
        assert all(e["data"]["backend"] == "snapshot" for e in ev if e["event"] == "verify")
        assert r["system_seconds"] == pytest.approx(next(e for e in ev if e["event"] == "done")["data"]["system_seconds_so_far"])
        assert "CC BY-NC-SA" in render_memo(r, v)


def test_mutating_a_cited_row_turns_receipt_red(db, tmp_path):
    r = run_question("olist_q1", db, "t-mut", tmp_path)
    c = next(x for x in r["claims"] if x["id"] == "kpi_period")
    assert verify_claims(db, [c])["all_green"]
    db.con.execute("UPDATE ol_orders SET late = NOT late WHERE order_id = ?", [c["row_ids"][0]])
    rec = verify_claims(db, [c])["receipts"][0]
    assert rec["status"] == "red"


def test_value_change_turns_receipt_red(db, tmp_path):
    r = run_question("olist_q2", db, "t-val", tmp_path)
    c = next(x for x in r["claims"] if x["id"] == "q2_transit_t")
    db.con.execute("UPDATE ol_orders SET transit_days = transit_days * 2 WHERE purchase_date BETWEEN DATE '2017-11-01' AND DATE '2017-11-30'")
    assert verify_claims(db, [c])["receipts"][0]["status"] == "red"


def test_why_diff_comes_only_from_trace_events(db, tmp_path):
    r = run_question("olist_q3", db, "t-wd", tmp_path)
    p = tmp_path / "trace-t-wd.jsonl"
    assert why_diff(p) == r["why_diff"]
    # Rewrite one recorded outcome in the trace file: the why-diff follows the file, not the run's memory.
    lines = [json.loads(l) for l in p.read_text().splitlines()]
    for e in lines:
        if e["event"] == "hypothesis_update" and e["data"]["evidence_id"] == "q3_late":
            e["data"]["hyp_outcome"] = "refutes"
    p.write_text("\n".join(json.dumps(e) for e in lines) + "\n")
    assert next(h for h in why_diff(p)["hypotheses"] if h["hyp"] == "H_late")["after"] == "refuted"


def test_sensitivity_is_deterministic(db, tmp_path):
    a = run_question("olist_q3", db, "t-s1", tmp_path)["sensitivity"]
    b = run_question("olist_q3", db, "t-s2", tmp_path)["sensitivity"]
    assert a == b
    assert {s["drop_source"] for s in a["by_source"]} == set(om.TABLES)
    assert next(s for s in a["by_source"] if s["drop_source"] == "ol_orders")["top_cause"] is None


def test_zetaris_render_prefixes_olist_tables():
    sql, params = om.metric_sql("olist.low_review_rate", {"window": ["2017-01-01", "2018-08-31"], "group": "interstate"})
    out = render(sql, params, "olist.", om.TABLES)
    for t in om.TABLES:
        assert f"olist.{t}" in out
    assert "?" not in out and "olist.olist." not in out


def test_api_verify_olist(db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.api as api
    import app.olist.backend as ob
    r = run_question("olist_q1", db, "t-api", tmp_path)
    monkeypatch.setattr(ob, "olist_backend", lambda: db)
    res = TestClient(api.app).post("/verify", json={"claims": r["claims"], "dataset": "olist"}).json()
    assert res["all_green"] and res["backend"] == "snapshot"
