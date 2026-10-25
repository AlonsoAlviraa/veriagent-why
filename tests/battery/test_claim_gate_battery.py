"""Claim Gate + POST /verify receipts over a generated grid of real claims on the DuckDB snapshot.

For every (metric, segment, window) cell the true value is computed by independent SQL (not via
app.checks), then: the exact claim must be green; a value shifted beyond tolerance must be red; a value
shifted inside tolerance must stay green; tampered/foreign/missing row ids must be red; a tampered SQL
definition (unsupported metric/segment column) must be red, never green."""
import datetime as dt, itertools, random
import pytest
from app.checks.claims import check_claim, metric_sql, RATE_TOL_PP, AMOUNT_TOL, check_narrative
from app.verify import verify_claim, verify_claims

CARRIERS = ["CarrierA", "CarrierB", "CarrierC"]
REGIONS = ["North", "South", "East", "West"]
CATS = ["apparel", "beauty", "electronics", "home"]
D0 = dt.date(2026, 9, 15)
WINDOWS = [(0, 29), (0, 6), (7, 13), (14, 20), (21, 29), (0, 14), (15, 29)]
SEGMENTS = ([{}] + [{"carrier": c} for c in CARRIERS] + [{"region": r} for r in REGIONS] + [{"category": c} for c in CATS]
            + [{"carrier": c, "region": r} for c, r in itertools.product(CARRIERS, REGIONS)])
METRICS = ["on_time_rate", "late_count"]
FROM = "v_logistics l JOIN v_orders o USING(order_id)"
COL = {"carrier": "l.carrier", "region": "l.region", "category": "o.category"}


def win(w):
    return [str(D0 + dt.timedelta(days=w[0])), str(D0 + dt.timedelta(days=w[1]))]


def truth(db, metric, seg, window):
    """Independent re-implementation (string-built SQL, not app.checks.metric_sql)."""
    w = [f"l.ship_date >= DATE '{window[0]}'", f"l.ship_date <= DATE '{window[1]}'"] + [f"{COL[k]} = '{v}'" for k, v in seg.items()]
    rows = db.query(f"SELECT l.shipment_id AS id, l.on_time AS ok FROM {FROM} WHERE {' AND '.join(w)} ORDER BY l.shipment_id")
    if not rows:
        return None, []
    late = sum(0 if r["ok"] else 1 for r in rows)
    val = 100.0 * (len(rows) - late) / len(rows) if metric == "on_time_rate" else float(late)
    return val, [r["id"] for r in rows]


CELLS = [(m, s, w) for m in METRICS for s in SEGMENTS for w in WINDOWS]


def cid(c):
    m, s, w = c
    return f"{m}-{'_'.join(f'{k}={v}' for k, v in s.items()) or 'all'}-d{w[0]}_{w[1]}"


@pytest.fixture(scope="module")
def grid(snap):
    out = {}
    for c in CELLS:
        m, s, w = c
        v, ids = truth(snap, m, s, win(w))
        out[cid(c)] = (m, s, win(w), v, ids)
    return out


def claim(m, s, window, value, ids, i="c"):
    return {"id": i, "metric": m, "segment": dict(s), "window": window, "value": value, "row_ids": ids}


@pytest.mark.parametrize("c", CELLS, ids=cid)
def test_exact_claim_green_and_matches_independent_sql(snap, grid, c):
    m, s, window, v, ids = grid[cid(c)]
    if v is None:
        pytest.skip("empty cell")
    r = verify_claim(snap, claim(m, s, window, round(v, 2), ids[:5]))
    assert r["status"] == "green", r["reasons"]
    assert abs(r["db_value"] - v) < 1e-9
    assert r["backend"] == "snapshot" and r["sql"].startswith("SELECT") and len(r["sql_sha"]) == 16


@pytest.mark.parametrize("c", CELLS, ids=cid)
def test_value_shift_beyond_tolerance_is_red(snap, grid, c):
    m, s, window, v, ids = grid[cid(c)]
    if v is None:
        pytest.skip("empty cell")
    tol = RATE_TOL_PP if m.endswith("_rate") else abs(v) * AMOUNT_TOL
    for sign in (1, -1):
        bad = v + sign * (tol + max(0.6, 0.02 * abs(v)))
        r = verify_claim(snap, claim(m, s, window, bad, ids[:5]))
        assert r["status"] == "red" and any("!= db" in x for x in r["reasons"]), (bad, v)


@pytest.mark.parametrize("c", CELLS, ids=cid)
def test_value_inside_tolerance_stays_green(snap, grid, c):
    m, s, window, v, ids = grid[cid(c)]
    if v is None:
        pytest.skip("empty cell")
    tol = RATE_TOL_PP if m.endswith("_rate") else abs(v) * AMOUNT_TOL
    r = verify_claim(snap, claim(m, s, window, v + 0.5 * tol, ids[:3]))
    assert r["status"] == "green", r["reasons"]


@pytest.mark.parametrize("c", CELLS, ids=cid)
def test_tampered_row_ids_are_red(snap, grid, c):
    m, s, window, v, ids = grid[cid(c)]
    if v is None:
        pytest.skip("empty cell")
    good = ids[:3]
    # 1) non-existent id
    r = verify_claim(snap, claim(m, s, window, v, good + ["NOPE-999999"]))
    assert r["status"] == "red" and any("not found" in x for x in r["reasons"])
    # 2) no cited rows at all
    r = verify_claim(snap, claim(m, s, window, v, []))
    assert r["status"] == "red" and "no cited rows" in r["reasons"]


@pytest.mark.parametrize("c", [c for c in CELLS if c[1] and c[2] != (0, 29)], ids=cid)
def test_row_from_other_segment_or_window_is_red(snap, grid, c):
    m, s, window, v, ids = grid[cid(c)]
    if v is None:
        pytest.skip("empty cell")
    # a real row from the complement (other segment value or outside the window)
    allw = [str(D0), str(D0 + dt.timedelta(days=29))]
    _, every = truth(snap, m, {}, allw)
    foreign = sorted(set(every) - set(ids))
    assert foreign
    r = verify_claim(snap, claim(m, s, window, v, ids[:2] + [foreign[len(foreign) // 2]]))
    assert r["status"] == "red" and any("does not match" in x for x in r["reasons"])


TAMPER = [("metric", "on_time_rate; DROP TABLE t_logistics"), ("metric", "revenue"), ("metric", "late_count--"),
          ("segment", {"carrier OR 1=1": "x"}), ("segment", {"customer": "a"}), ("segment", {"l.carrier": "CarrierA"})]


@pytest.mark.parametrize("field,val", TAMPER, ids=[f"{a}-{i}" for i, (a, _) in enumerate(TAMPER)])
@pytest.mark.parametrize("w", WINDOWS[:3])
def test_tampered_sql_definition_never_green(snap, grid, field, val, w):
    m, s, window, v, ids = grid[cid(("on_time_rate", {}, w))]
    c = claim(m, s, window, v, ids[:2])
    c[field] = val
    r = verify_claim(snap, c)
    assert r["status"] == "red" and r["sql"] is None
    assert snap.query("SELECT COUNT(*) n FROM v_logistics")[0]["n"] > 0  # nothing dropped


@pytest.mark.parametrize("w", WINDOWS)
def test_sql_hash_is_stable_and_sensitive(snap, grid, w):
    m, s, window, v, ids = grid[cid(("on_time_rate", {}, w))]
    a = verify_claim(snap, claim(m, s, window, v, ids[:2]))
    b = verify_claim(snap, claim(m, s, window, v + 0.1, ids[:2]))
    assert a["sql_sha"] == b["sql_sha"]  # hash covers SQL+params, not the printed value
    other = [window[0], str(D0 + dt.timedelta(days=29))] if window[1] != str(D0 + dt.timedelta(days=29)) else [str(D0 + dt.timedelta(days=1)), window[1]]
    c = verify_claim(snap, claim(m, s, other, v, ids[:2]))
    assert c["sql_sha"] != a["sql_sha"]


def _mix(seed):
    rng = random.Random(seed)
    return rng, [rng.choice(CELLS) for _ in range(rng.randint(1, 6))]


@pytest.mark.parametrize("seed", range(60))
def test_receipt_summary_and_all_green_consistency(snap, grid, seed, tmp_path):
    rng, cells = _mix(seed)
    claims, expect = [], []
    for k, c in enumerate(cells):
        m, s, window, v, ids = grid[cid(c)]
        kind = rng.choice(["green", "red", "unverifiable"]) if v is not None else "unverifiable"
        if kind == "unverifiable":
            claims.append({"id": f"n{k}", "text": "narrative"})
        elif kind == "green":
            claims.append(claim(m, s, window, v, ids[:2], f"g{k}"))
        else:
            claims.append(claim(m, s, window, v + 50, ids[:2], f"r{k}"))
        expect.append(kind)
    out = verify_claims(snap, claims, run_id=f"bat-{seed}", log_dir=tmp_path)
    assert [r["status"] for r in out["receipts"]] == expect
    assert out["summary"] == {k: expect.count(k) for k in ("green", "red", "unverifiable")}
    assert out["all_green"] == all(e == "green" for e in expect)
    lines = (tmp_path / f"trace-bat-{seed}.jsonl").read_text().splitlines()
    assert len(lines) == len(claims)


@pytest.mark.parametrize("n", range(40))
def test_narrative_numbers_must_be_approved(n):
    rng = random.Random(n)
    facts = [f"{round(rng.uniform(1, 999), 1)}" for _ in range(4)]
    ok_text = f"On-time was {facts[0]} and late was {facts[1]}."
    assert check_narrative(ok_text, facts)["passed"]
    bad = round(float(facts[0]) + rng.choice([1, -1]) * rng.uniform(0.2, 50), 1)
    if all(abs(bad - float(f)) > 0.05 for f in facts):
        assert not check_narrative(f"On-time was {bad}.", facts)["passed"]
