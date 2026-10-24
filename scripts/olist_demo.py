"""Olist demo: run the 3 questions, verify every claim (POST /verify logic), write memos.

  python scripts/olist_demo.py                    # DuckDB snapshot (data/olist/olist.duckdb)
  python scripts/olist_demo.py --backend zetaris  # Zetaris JDBC, container `olist` (scripts/olist_zetaris_load.py)
  python scripts/olist_demo.py --mutate           # also: flip one cited row in the source -> RED -> restore -> GREEN

Writes logs/olist/<backend>/memo-<qid>.md, result-*.json and trace-*.jsonl (CC BY-NC-SA 4.0, Olist).
Exit 0 only if every claim is green (and, with --mutate, the sequence is green -> red -> green;
with --backend zetaris every receipt must carry badge "zetaris"). $0: no model calls. Never prints secrets.
"""
from __future__ import annotations
import argparse, json, os, shutil, sys, tempfile, time
from _zetaris_common import ROOT, load_dotenv, short


def pg_cfg():
    return dict(host=os.environ.get("VA_PG_HOST", "localhost"), port=int(os.environ.get("VA_PG_PORT", "5433")),
                dbname=os.environ.get("VA_PG_DB", "veriagent"), user=os.environ.get("VA_PG_USER", "veriagent"),
                password=os.environ.get("VA_PG_PASSWORD", ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", choices=["snapshot", "zetaris"], default="snapshot")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    load_dotenv()
    from app.olist.backend import OLIST_DB, OlistSnapshot, OlistZetaris
    from app.olist.investigate import render_memo, run_question
    from app.olist.questions import QUESTIONS
    from app.verify import verify_claims
    out = ROOT / (a.out or f"logs/olist/{a.backend}")
    out.mkdir(parents=True, exist_ok=True)
    if a.backend == "zetaris":
        os.environ["SAMPLE_MODE"] = "false"; os.environ["ZETARIS_BACKEND"] = "zetaris"
        db = OlistZetaris()
    else:
        if not OLIST_DB.exists():
            import subprocess
            subprocess.run([sys.executable, str(ROOT / "scripts" / "olist_fetch.py")], check=True)
        db = OlistSnapshot()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ok, results = True, {}
    for qid in QUESTIONS:
        rid = f"{qid}-{a.backend}-{stamp}"
        r = run_question(qid, db, rid, out)
        t0 = time.time()
        v = verify_claims(db, r["claims"], run_id=rid, log_dir=out)
        v["elapsed_s"] = round(time.time() - t0, 3)
        (out / f"memo-{qid}.md").write_text(render_memo(r, v))
        bad = [x["claim_id"] for x in v["receipts"] if x["status"] != "green"]
        badges = {x["backend"] for x in v["receipts"]}
        print(f"{qid}: top={r['top_cause']} claims={len(r['claims'])} green={v['summary']['green']} red={v['summary']['red']} "
              f"backend={','.join(sorted(badges))} system_s={r['system_seconds']} verify_s={v['elapsed_s']}")
        ok &= not bad and (a.backend == "snapshot" or badges == {"zetaris"})
        results[qid] = (r, rid)
    if a.mutate:
        r, rid = results["olist_q1"]
        c = next(x for x in r["claims"] if x["id"] == "kpi_period")
        oid = c["row_ids"][0]
        if a.backend == "zetaris":
            import psycopg
            def flip():
                with psycopg.connect(**pg_cfg()) as pg, pg.cursor() as cur:
                    cur.execute("UPDATE ol_orders SET late = NOT late WHERE order_id = %s", (oid,)); pg.commit()
            vdb = lambda: db
        else:
            tmp = os.path.join(tempfile.mkdtemp(), "olist.duckdb"); shutil.copy(OLIST_DB, tmp)
            def flip():
                import duckdb
                con = duckdb.connect(tmp); con.execute("UPDATE ol_orders SET late = NOT late WHERE order_id = ?", [oid]); con.close()
            vdb = lambda: OlistSnapshot(tmp)
        seq = []
        def step(label):
            d = vdb(); v = verify_claims(d, [c], run_id=rid, log_dir=out)
            if a.backend == "snapshot": d.con.close()
            x = v["receipts"][0]; seq.append((x["backend"], x["status"]))
            print(f"[{label}] {c['id']} memo={c['value']} db={x['db_value']} backend={x['backend']} -> {x['status'].upper()} {x['reasons'] or ''}")
        step("verify")
        try:
            flip(); print(f"mutated ol_orders.late for cited order {oid[:8]}... in the source")
            step("after mutation")
        finally:
            flip(); print("restored")
        step("after restore")
        ok &= [s for _, s in seq] == ["green", "red", "green"] and (a.backend == "snapshot" or all(b == "zetaris" for b, _ in seq))
    print(f"outputs: {out}")
    print("OLIST OK" if ok else "OLIST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("ERROR:", short(e), file=sys.stderr); sys.exit(1)
