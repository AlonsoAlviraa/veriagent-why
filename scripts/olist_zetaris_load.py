"""Load the Olist demo tables into a local Zetaris (same cookbook pattern as scripts/zetaris_load.py).

Federation (two sources, joined by Zetaris at query time):
  source 1  PostgreSQL datasource `olist_pg`    -> ol_orders, ol_items, ol_reviews  (same Postgres as the main demo, port 5433)
  source 2  REST Lightning database `olist_rest` -> ol_sellers (scripts/zetaris_rest_source.py, must be running)
  unified   SchemaStore container `olist` with views ol_orders ... ol_sellers (OLIST_VIEW_PREFIX=olist.)

Data: data/olist/olist.duckdb built by scripts/olist_fetch.py (Olist, CC BY-NC-SA 4.0).
Idempotent. `--no-rest` puts ol_sellers in Postgres too. `--dry-run` prints the plan only.
Env: same as scripts/zetaris_load.py (.env). Never prints passwords.
"""
from __future__ import annotations
import argparse, os, subprocess, sys
from _zetaris_common import ROOT, load_dotenv, short
from zetaris_load import load_postgres, names, zsql

DS, RESTDB, CONTAINER = "olist_pg", "olist_rest", "olist"
PG = ["ol_orders", "ol_items", "ol_reviews"]
REST = ["ol_sellers"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-rest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    load_dotenv()
    db = ROOT / "data" / "olist" / "olist.duckdb"
    if not db.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "olist_fetch.py")], check=True)
    pg_t = PG + (REST if a.no_rest else [])
    rest_t = [] if a.no_rest else REST
    cfg = load_postgres(db, pg_t, a.dry_run)
    cur = None
    if not a.dry_run:
        from app.adapters.zetaris import jdbc_connect
        cur = jdbc_connect().cursor()
    zsql(cur, "SELECT 1", a.dry_run)
    pg_host = os.environ.get("VA_PG_HOST_FROM_ZETARIS", "host.docker.internal")
    if DS not in names(zsql(cur, "SHOW DATASOURCES", a.dry_run)):
        zsql(cur, f'CREATE DATASOURCE {DS} DESCRIBE BY "olist_public_ecommerce_postgres" OPTIONS ('
                  f'jdbcdriver "org.postgresql.Driver", jdbcurl "jdbc:postgresql://{pg_host}:{cfg["port"]}/{cfg["dbname"]}", '
                  f'username "{cfg["user"]}", password "{cfg["password"]}", fetchsize "5000")', a.dry_run)
    zsql(cur, "REGISTER DATASOURCE TABLES (" + ", ".join(f"'{t}'" for t in pg_t) + f") FROM {DS}", a.dry_run)
    if rest_t:
        if RESTDB not in names(zsql(cur, "SHOW LIGHTNING DATABASES", a.dry_run)):
            zsql(cur, f'CREATE LIGHTNING DATABASE {RESTDB} DESCRIBE BY "olist_sellers_rest"', a.dry_run)
        host = os.environ.get("VA_REST_HOST_FROM_ZETARIS", "host.docker.internal")
        port = os.environ.get("VA_REST_PORT", "8765")
        for t in rest_t:
            zsql(cur, f"DROP LIGHTNING DATABASE TABLE {RESTDB}.{t}_raw", a.dry_run,
                 ok_if=("not exist", "doesn't exist", "does not exist", "not found", "no such"))
            zsql(cur, f'CREATE LIGHTNING REST TABLE {t}_raw FROM {RESTDB} REQUEST(endpoint "http://{host}:{port}/{t}", '
                      f'method "get", response_type "json", http_encoding "URLENCODED") HEADER () BODY ()', a.dry_run)
    zsql(cur, f"CREATE SCHEMASTORE CONTAINER {CONTAINER}", a.dry_run)
    for t in pg_t:
        zsql(cur, f"CREATE OR REPLACE SCHEMASTORE VIEW {t} WITH CONTAINER {CONTAINER} AS SELECT * FROM {DS}.{t}", a.dry_run)
    for t in rest_t:
        zsql(cur, f"CREATE OR REPLACE SCHEMASTORE VIEW {t} WITH CONTAINER {CONTAINER} AS SELECT r.seller_id AS seller_id, "
                  f"r.seller_state AS seller_state FROM {RESTDB}.{t}_raw LATERAL VIEW explode(rows) AS r", a.dry_run)
    if not a.dry_run:
        import duckdb
        con = duckdb.connect(str(db), read_only=True)
        for t in pg_t + rest_t:
            local = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            cur.execute(f"SELECT COUNT(*) FROM {CONTAINER}.{t}")
            remote = int(str(cur.fetchall()[0][0]))
            print(f"check {CONTAINER}.{t}: zetaris={remote} local={local} {'OK' if remote == local else 'MISMATCH'}")
            if remote != local:
                return 1
    print("next: python scripts/olist_demo.py --backend zetaris --mutate")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("ERROR:", short(e), file=sys.stderr); sys.exit(1)
