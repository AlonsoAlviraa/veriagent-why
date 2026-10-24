"""Live receipt demo for the video: run -> verify (green) -> mutate one source row -> verify (red) -> restore -> verify (green).

  python scripts/verify_live_demo.py                    # Zetaris (ZETARIS_BACKEND=zetaris, .env), mutates Postgres v_logistics
  python scripts/verify_live_demo.py --backend snapshot # offline: same flow on a temp DuckDB copy (CI / no Zetaris)

The mutation goes to the SOURCE (Postgres behind the Zetaris datasource), and the re-verify goes back
through Zetaris JDBC, so a red receipt proves the query really re-executed through the federation.
The row is always restored (finally:). Exit 0 only if the sequence is green -> red -> green and, for
--backend zetaris, every receipt carries badge "zetaris". Never prints credentials.
"""
from __future__ import annotations
import argparse, json, os, shutil, sys, tempfile, uuid
from _zetaris_common import ROOT, load_dotenv, short


def pg_flip(ids: list[str]):
    import psycopg
    cfg = dict(host=os.environ.get("VA_PG_HOST", "localhost"), port=int(os.environ.get("VA_PG_PORT", "5433")),
               dbname=os.environ.get("VA_PG_DB", "veriagent"), user=os.environ.get("VA_PG_USER", "veriagent"),
               password=os.environ.get("VA_PG_PASSWORD", ""))
    with psycopg.connect(**cfg) as pg, pg.cursor() as cur:
        cur.execute("UPDATE v_logistics SET on_time = NOT on_time WHERE shipment_id = ANY(%s)", (ids,))
        pg.commit()


def duck_flip(path: str, ids: list[str]):
    import duckdb
    con = duckdb.connect(path)
    con.execute(f"UPDATE t_logistics SET on_time = NOT on_time WHERE shipment_id IN ({','.join('?' * len(ids))})", ids)
    con.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", choices=["zetaris", "snapshot"], default="zetaris")
    ap.add_argument("--input", default=str(ROOT / "input_examples" / "example_1.json"))
    a = ap.parse_args(argv)
    load_dotenv()
    from app.adapters.zetaris import SnapshotBackend, get_backend, SNAPSHOT
    from app.verify import verify_claims
    rid = f"verify-demo-{uuid.uuid4().hex[:6]}"
    if a.backend == "zetaris":
        os.environ["SAMPLE_MODE"] = "false"; os.environ["ZETARIS_BACKEND"] = "zetaris"
        os.environ.setdefault("LLM_PROVIDER", "sample")  # data-only demo: $0, no model calls unless .env says otherwise
        open_db, flip = (lambda: get_backend()), pg_flip
    else:
        os.environ["SAMPLE_MODE"] = "true"
        tmp = os.path.join(tempfile.mkdtemp(), "snap.duckdb")
        if not SNAPSHOT.exists():
            get_backend()  # builds data/snapshot.duckdb
        shutil.copy(SNAPSHOT, tmp)
        def open_db():
            return SnapshotBackend(tmp)
        flip = lambda ids: duck_flip(tmp, ids)
    from app.pipeline import run
    res = run(json.loads(open(a.input).read())["input"], rid)
    claims = res["output"]["result"]["claims"]
    if not claims:
        print("no gate-approved claims; nothing to verify"); return 1
    ids = claims[0]["row_ids"]
    seq = []

    def step(label):
        db = open_db()
        v = verify_claims(db, claims, run_id=rid, log_dir=ROOT / "logs")
        if hasattr(db, "con"):
            db.con.close()
        c0 = v["receipts"][0]
        print(f"[{label}] backend={v['backend']} claim={c0['claim_id']} memo={c0['memo_value']} db={c0['db_value']} -> {c0['status'].upper()}")
        seq.append((v["backend"], c0["status"]))

    step("verify")
    try:
        flip(ids); print(f"mutated on_time for {len(ids)} cited row(s) in the source")
        step("after mutation")
    finally:
        flip(ids); print("restored")  # NOT applied twice = original values
    step("after restore")
    print(f"trace: logs/trace-{rid}.jsonl (verify events appended)")
    ok = [s for _, s in seq] == ["green", "red", "green"] and (a.backend == "snapshot" or all(b == "zetaris" for b, _ in seq))
    print("DEMO OK" if ok else "DEMO FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("ERROR:", short(e), file=sys.stderr); sys.exit(1)
