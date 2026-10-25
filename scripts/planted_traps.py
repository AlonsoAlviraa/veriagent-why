"""Planted-trap evaluation of the Claim Gate (POST /verify) on the offline DuckDB snapshot.

Generates N seeded claims over (metric, segment, window) cells. Half are TRAPS (a planted error the gate
must turn red), half are CONTROLS (a correct claim, possibly rounded, that must stay green). Truth comes
from independent SQL, not from app.checks. Reports detection rate, false-alarm rate and Wilson 95% CIs,
per trap type. Offline, no network, no spend, deterministic for a given --seed.

    python scripts/planted_traps.py --n 800 --seed 20261025 --out docs/test_battery/planted_traps.json
"""
import argparse, datetime as dt, itertools, json, math, random, subprocess, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.adapters.zetaris import SnapshotBackend  # noqa: E402
from app.checks.claims import RATE_TOL_PP, AMOUNT_TOL  # noqa: E402
from app.verify import verify_claim  # noqa: E402

CARRIERS, REGIONS, CATS = ["CarrierA", "CarrierB", "CarrierC"], ["North", "South", "East", "West"], ["apparel", "beauty", "electronics", "home"]
SEGS = ([{}] + [{"carrier": c} for c in CARRIERS] + [{"region": r} for r in REGIONS] + [{"category": c} for c in CATS]
        + [{"carrier": c, "region": r} for c, r in itertools.product(CARRIERS, REGIONS)])
COL = {"carrier": "l.carrier", "region": "l.region", "category": "o.category"}
D0 = dt.date(2026, 9, 15)
TRAPS = ["shift_large", "shift_just_outside_tol", "ratio_as_percent", "segment_swap", "window_swap", "foreign_row_ids",
         "fabricated_row_ids", "metric_swap", "inverse_rate"]
CONTROLS = ["exact", "rounded_1dp", "rounded_0dp_count", "jitter_inside_tol"]


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, round(c - h, 4)), min(1.0, round(c + h, 4))]


def truth(db, metric, seg, w):
    wh = [f"l.ship_date >= DATE '{w[0]}'", f"l.ship_date <= DATE '{w[1]}'"] + [f"{COL[k]} = '{v}'" for k, v in seg.items()]
    rows = db.query("SELECT l.shipment_id AS id, l.on_time AS ok FROM v_logistics l JOIN v_orders o USING(order_id) WHERE "
                    + " AND ".join(wh) + " ORDER BY l.shipment_id")
    if not rows:
        return None, []
    late = sum(0 if r["ok"] else 1 for r in rows)
    return (100.0 * (len(rows) - late) / len(rows) if metric == "on_time_rate" else float(late)), [r["id"] for r in rows]


def tol(m, v):
    return RATE_TOL_PP if m.endswith("_rate") else abs(v) * AMOUNT_TOL


def narrative(r, n):
    """Narrative check (check_narrative): numbers in prose must match an approved fact within 0.05.
    Controls write a true fact in common business formats; traps write a wrong number (|error| > 0.05)."""
    from app.checks.claims import check_narrative
    CF = {"plain": lambda v: f"{v:g}", "pct_1dp": lambda v: f"{v:.1f}%", "pct_2dp": lambda v: f"{v:.2f}%",
          "thousands_sep": lambda v: f"{v:,.0f}", "with_year": lambda v: f"In 2026 the value was {v:g}",
          "with_date": lambda v: f"On Sep 15 the value was {v:g}", "ratio_form": lambda v: f"{v / 100:.4f}"}
    TF = {"wrong_plain": lambda v, r: f"{v + r.choice([1, -1]) * r.uniform(0.2, 20):.2f}",
          "wrong_pct": lambda v, r: f"{v + r.choice([1, -1]) * r.uniform(0.2, 20):.1f}%",
          "wrong_thousands_sep": lambda v, r: f"{v + r.randint(1000, 5000):,.0f}",
          "digit_transposition": lambda v, r: (lambda s: s[1] + s[0] + s[2:] if s[0] != s[1] else str(int(s) + 1))(f"{int(v):d}"),
          "spelled_out_wrong": lambda v, r: r.choice(["roughly one thousand", "about two hundred", "nearly ninety percent"])}
    out = defaultdict(Counter)
    for i in range(n):
        v = round(r.uniform(1000, 9999), 0) if r.random() < 0.4 else round(r.uniform(50, 99.99), 2)
        facts = [f"metric value {v}"]
        if i % 2:
            k = r.choice(list(CF)); txt = CF[k](v); kind = "control"
            if k == "thousands_sep" and v < 1000: k, txt = "plain", CF["plain"](v)
            if k == "ratio_form" and v >= 1000: k, txt = "plain", CF["plain"](v)
        else:
            k = r.choice(list(TF)); txt = TF[k](v, r); kind = "trap"
        flagged = not check_narrative(f"Summary: {txt}.", facts)["passed"]
        out[(kind, k)]["flagged" if flagged else "passed"] += 1
    res = {}
    for kind in ("trap", "control"):
        f = sum(c["flagged"] for (kk, _), c in out.items() if kk == kind); m = sum(sum(c.values()) for (kk, _), c in out.items() if kk == kind)
        res[f"{kind}_flagged"] = [f, m, round(f / m, 4), wilson(f, m)]
    res["by_type"] = {f"{kk}/{k}": {**dict(c), "n": sum(c.values()), "rate_flagged": round(c["flagged"] / sum(c.values()), 4),
                                    "ci95": wilson(c["flagged"], sum(c.values()))} for (kk, k), c in sorted(out.items())}
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=800); ap.add_argument("--seed", type=int, default=20261025)
    ap.add_argument("--out", default="docs/test_battery/planted_traps.json"); a = ap.parse_args(argv)
    snap = Path(tempfile.mkdtemp()) / "snap.duckdb"
    subprocess.run([sys.executable, str(ROOT / "scripts/make_data.py"), "--out", str(snap)], check=True, capture_output=True)
    db = SnapshotBackend(snap); r = random.Random(a.seed)
    all_ids = [x["id"] for x in db.query("SELECT shipment_id AS id FROM v_logistics ORDER BY 1")]
    items = []
    while len(items) < a.n:
        m = r.choice(["on_time_rate", "late_count"]); s = r.choice(SEGS)
        lo = r.randint(0, 25); hi = r.randint(lo + 3, 29); w = [str(D0 + dt.timedelta(days=lo)), str(D0 + dt.timedelta(days=hi))]
        v, ids = truth(db, m, s, w)
        if v is None or len(ids) < 5 or (m == "late_count" and v < 5):
            continue
        cited = r.sample(ids, min(5, len(ids)))
        is_trap = len(items) % 2 == 0
        c = {"id": f"p{len(items)}", "metric": m, "segment": dict(s), "window": w, "value": v, "row_ids": cited}
        if is_trap:
            t = TRAPS[(len(items) // 2) % len(TRAPS)]
            if t == "shift_large":
                c["value"] = v + r.choice([1, -1]) * max(3 * tol(m, v) + 2, 0.15 * abs(v))
            elif t == "shift_just_outside_tol":
                c["value"] = v + r.choice([1, -1]) * (tol(m, v) * 1.5 + (0.3 if m == "on_time_rate" else 1))
            elif t == "ratio_as_percent":
                if m != "on_time_rate":
                    continue
                c["value"] = v / 100.0
            elif t in ("segment_swap", "window_swap", "metric_swap"):
                if t == "segment_swap":
                    s2 = r.choice([x for x in SEGS if x != s]); v2, _ = truth(db, m, s2, w)
                elif t == "window_swap":
                    lo2 = r.randint(0, 25); w2 = [str(D0 + dt.timedelta(days=lo2)), str(D0 + dt.timedelta(days=r.randint(lo2 + 3, 29)))]
                    v2, _ = truth(db, m, s, w2)
                else:
                    m2 = "late_count" if m == "on_time_rate" else "on_time_rate"; v2, _ = truth(db, m2, s, w)
                if v2 is None or abs(v2 - v) <= tol(m, v) + 1e-9:
                    continue  # not a real error: the swapped value happens to agree
                c["value"] = v2
            elif t == "foreign_row_ids":
                out = [i for i in all_ids if i not in set(ids)]
                c["row_ids"] = cited[:3] + r.sample(out, 2)
            elif t == "fabricated_row_ids":
                c["row_ids"] = cited[:3] + [f"S-FAKE-{r.randint(10**5, 10**6)}" for _ in range(2)]
            elif t == "inverse_rate":
                if m != "on_time_rate" or abs(v - 50) < 5:
                    continue
                c["value"] = 100 - v
        else:
            t = CONTROLS[(len(items) // 2) % len(CONTROLS)]
            if t == "rounded_1dp":
                c["value"] = round(v, 1)
            elif t == "rounded_0dp_count":
                c["value"] = round(v) if m == "late_count" else round(v, 1)
            elif t == "jitter_inside_tol":
                c["value"] = v + r.uniform(-0.8, 0.8) * tol(m, v)
        res = verify_claim(db, c)
        items.append({"id": c["id"], "kind": "trap" if is_trap else "control", "type": t, "metric": m, "segment": s, "window": w,
                      "true_value": v, "claimed": c["value"], "status": res["status"]})
    db.con.close()
    by = defaultdict(Counter)
    for it in items:
        by[(it["kind"], it["type"])][it["status"]] += 1
    traps = [i for i in items if i["kind"] == "trap"]; ctrl = [i for i in items if i["kind"] == "control"]
    det = sum(i["status"] == "red" for i in traps); fa = sum(i["status"] == "red" for i in ctrl)
    nongreen_c = sum(i["status"] != "green" for i in ctrl); green_t = sum(i["status"] == "green" for i in traps)
    rep = {"seed": a.seed, "n": len(items), "n_traps": len(traps), "n_controls": len(ctrl),
           "detection_red": [det, len(traps), round(det / len(traps), 4), wilson(det, len(traps))],
           "traps_passed_green (missed)": [green_t, len(traps), round(green_t / len(traps), 4), wilson(green_t, len(traps))],
           "false_alarm_red": [fa, len(ctrl), round(fa / len(ctrl), 4), wilson(fa, len(ctrl))],
           "controls_not_green": [nongreen_c, len(ctrl), round(nongreen_c / len(ctrl), 4), wilson(nongreen_c, len(ctrl))],
           "by_type": {f"{k}/{t}": {**dict(cn), "n": sum(cn.values()), "rate_red": round(cn["red"] / sum(cn.values()), 4),
                                     "ci95_red": wilson(cn["red"], sum(cn.values()))} for (k, t), cn in sorted(by.items())},
           "examples_missed": [i for i in traps if i["status"] != "red"][:20],
           "examples_false_alarm": [i for i in ctrl if i["status"] != "green"][:20]}
    rep["narrative"] = narrative(random.Random(a.seed + 1), a.n)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({k: v for k, v in rep.items() if not k.startswith("examples")}, indent=1))


if __name__ == "__main__":
    main()
