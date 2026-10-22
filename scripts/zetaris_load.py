"""Load the 5 synthetic views into a local Zetaris, following the zetaris/getting-started cookbook.

Federation (two different sources, joined by Zetaris at query time):
  source 1  PostgreSQL datasource  `veriagent_pg`   -> v_orders, v_returns, v_logistics
            (CREATE DATASOURCE ... jdbcdriver org.postgresql.Driver; REGISTER DATASOURCE TABLES)
  source 2  REST Lightning database `veriagent_rest` -> v_tickets, v_promotions
            (CREATE LIGHTNING DATABASE; CREATE LIGHTNING REST TABLE over scripts/zetaris_rest_source.py)
  unified   SchemaStore container `veriagent` with views v_orders ... v_promotions
            (CREATE OR REPLACE SCHEMASTORE VIEW), which the app queries (ZETARIS_VIEW_PREFIX=veriagent.)

Why not CSV files: the cookbook says a file on your laptop may be out of reach for Zetaris (file tables
need S3/Azure/GCS/HDFS paths), so local CSVs are not a supported path. `--no-rest` puts all 5 views in
Postgres (still a real Zetaris datasource, but a single source).

Idempotent: Postgres tables are dropped and reloaded; Zetaris objects are created only if missing,
REST tables are dropped and recreated, views use OR REPLACE. One SQL statement per JDBC call.
Windows-friendly: pure Python, pathlib, no shell tools.

Env (from .env or exported): ZETARIS_JDBC_URL ZETARIS_USER ZETARIS_PASSWORD ZETARIS_JDBC_JAR,
VA_PG_HOST VA_PG_PORT VA_PG_DB VA_PG_USER VA_PG_PASSWORD (loader -> Postgres, from the host),
VA_PG_HOST_FROM_ZETARIS (Postgres host as seen by the Zetaris containers, default host.docker.internal),
VA_REST_HOST_FROM_ZETARIS (default host.docker.internal), VA_REST_PORT (default 8765).
"""
from __future__ import annotations
import argparse, os, sys
from _zetaris_common import ROOT, load_dotenv, local_counts, short

PG_VIEWS = ["v_orders", "v_returns", "v_logistics"]
REST_VIEWS = ["v_tickets", "v_promotions"]
TYPES = {"VARCHAR": "TEXT", "DATE": "DATE", "INTEGER": "INTEGER", "BIGINT": "BIGINT", "DOUBLE": "DOUBLE PRECISION",
         "BOOLEAN": "BOOLEAN"}
DS, RESTDB, CONTAINER = "veriagent_pg", "veriagent_rest", "veriagent"


def q(s: str) -> str:
    return '"' + s.replace('"', '') + '"'


def load_postgres(snapshot, views, dry):
    import duckdb
    con = duckdb.connect(str(snapshot), read_only=True)
    cfg = dict(host=os.environ.get("VA_PG_HOST", "localhost"), port=int(os.environ.get("VA_PG_PORT", "5433")),
               dbname=os.environ.get("VA_PG_DB", "veriagent"), user=os.environ.get("VA_PG_USER", "veriagent"),
               password=os.environ.get("VA_PG_PASSWORD", ""))
    if dry:
        print(f"[dry-run] would load {views} into postgres {cfg['host']}:{cfg['port']}/{cfg['dbname']}")
        return cfg
    import psycopg
    with psycopg.connect(**cfg) as pg, pg.cursor() as cur:
        for v in views:
            cols = con.execute(f"DESCRIBE {v}").fetchall()
            cur.execute(f"DROP TABLE IF EXISTS {v}")
            cur.execute(f"CREATE TABLE {v} (" + ", ".join(f"{c[0]} {TYPES[c[1]]}" for c in cols) + ")")
            rows = con.execute(f"SELECT * FROM {v}").fetchall()
            with cur.copy(f"COPY {v} ({', '.join(c[0] for c in cols)}) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row(r)
            print(f"postgres: {v} <- {len(rows)} rows")
        pg.commit()
    return cfg


def zsql(cur, sql, dry, ok_if=("already exist", "exists")):
    """Run one Lightning statement. Errors whose text matches ok_if are treated as 'already there'."""
    shown = sql if "password" not in sql.lower() else sql.split("OPTIONS")[0] + "OPTIONS (... redacted ...)"
    print(("[dry-run] " if dry else "zetaris> ") + " ".join(shown.split())[:160])
    if dry:
        return None
    try:
        cur.execute(sql)
        try:
            return cur.fetchall()
        except Exception:
            return None
    except Exception as e:
        if any(k in str(e).lower() for k in ok_if):
            print("   (already exists, kept)")
            return None
        raise


def names(rows):
    return {str(r[0]).lower() for r in rows or []}


def view_sql(v, source):
    if source == "pg":
        return f"CREATE OR REPLACE SCHEMASTORE VIEW {v} WITH CONTAINER {CONTAINER} AS SELECT * FROM {DS}.{v}"
    cols = {"v_tickets": "r.ticket_id AS ticket_id, r.order_id AS order_id, CAST(r.created_date AS DATE) AS created_date, r.text AS text",
            "v_promotions": "r.promo_id AS promo_id, r.name AS name, CAST(r.start_date AS DATE) AS start_date, "
                            "CAST(r.end_date AS DATE) AS end_date, r.category AS category, r.region AS region, "
                            "CAST(r.discount_pct AS DOUBLE) AS discount_pct"}[v]
    return (f"CREATE OR REPLACE SCHEMASTORE VIEW {v} WITH CONTAINER {CONTAINER} AS SELECT {cols} "
            f"FROM {RESTDB}.{v}_raw LATERAL VIEW explode(rows) AS r")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", default=str(ROOT / "data" / "snapshot.duckdb"))
    ap.add_argument("--no-rest", action="store_true", help="single source: all 5 views in Postgres")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and SQL, touch nothing")
    a = ap.parse_args(argv)
    load_dotenv()
    from pathlib import Path
    snap = Path(a.snapshot)
    if not snap.exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_data.py")], check=True)
    pg_views = PG_VIEWS + ([] if not a.no_rest else REST_VIEWS)
    rest_views = [] if a.no_rest else REST_VIEWS
    cfg = load_postgres(snap, pg_views, a.dry_run)

    cur = None
    if not a.dry_run:
        from app.adapters.zetaris import jdbc_connect
        cur = jdbc_connect().cursor()
    zsql(cur, "SELECT 1", a.dry_run)
    pg_host = os.environ.get("VA_PG_HOST_FROM_ZETARIS", "host.docker.internal")
    existing = names(zsql(cur, "SHOW DATASOURCES", a.dry_run))
    if DS not in existing:
        zsql(cur, f'CREATE DATASOURCE {DS} DESCRIBE BY "VeriAgent Why synthetic shop (Postgres)" OPTIONS ('
                  f'jdbcdriver "org.postgresql.Driver", jdbcurl "jdbc:postgresql://{pg_host}:{cfg["port"]}/{cfg["dbname"]}", '
                  f'username "{cfg["user"]}", password "{cfg["password"]}", fetchsize "1000")', a.dry_run)
    zsql(cur, f"REGISTER DATASOURCE TABLES (" + ", ".join(f"'{v}'" for v in pg_views) + f") FROM {DS}", a.dry_run)

    if rest_views:
        if RESTDB not in names(zsql(cur, "SHOW LIGHTNING DATABASES", a.dry_run)):
            zsql(cur, f'CREATE LIGHTNING DATABASE {RESTDB} DESCRIBE BY "VeriAgent Why tickets+promotions (REST)"', a.dry_run)
        host = os.environ.get("VA_REST_HOST_FROM_ZETARIS", "host.docker.internal")
        port = os.environ.get("VA_REST_PORT", "8765")
        for v in rest_views:
            zsql(cur, f"DROP LIGHTNING DATABASE TABLE {RESTDB}.{v}_raw", a.dry_run, ok_if=("not exist", "not found", "no such"))
            zsql(cur, f'CREATE LIGHTNING REST TABLE {v}_raw FROM {RESTDB} REQUEST(endpoint "http://{host}:{port}/{v}", '
                      f'method "get", response_type "json", http_encoding "URLENCODED") HEADER () BODY ()', a.dry_run)

    zsql(cur, f"CREATE SCHEMASTORE CONTAINER {CONTAINER}", a.dry_run)
    for v in pg_views:
        zsql(cur, view_sql(v, "pg"), a.dry_run)
    for v in rest_views:
        zsql(cur, view_sql(v, "rest"), a.dry_run)

    print("\nexpected row counts (local snapshot):", local_counts(snap))
    print("next: python scripts/zetaris_check.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # keep Java stack traces and secrets out of the console
        print("ERROR:", short(e), file=sys.stderr)
        sys.exit(1)
