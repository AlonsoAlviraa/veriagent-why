"""Check the Zetaris JDBC connection: SELECT 1, list datasources / Lightning databases / views,
and compare the row counts of the 5 views in Zetaris against the local snapshot. Exit 0 only if all match."""
from __future__ import annotations
import sys
from _zetaris_common import ROOT, load_dotenv, local_counts, short


def main(conn=None) -> int:
    load_dotenv()
    from app.adapters.zetaris import ZetarisJdbcBackend, VIEWS
    b = ZetarisJdbcBackend(conn=conn)
    one = b.execute("SELECT 1 AS one")
    print("SELECT 1 ->", one)
    ok = bool(one) and list(one[0].values())[0] == 1
    for stmt in ("SHOW DATASOURCES", "SHOW LIGHTNING DATABASES", "SHOW DATASOURCE VIEWS"):
        try:
            rows = b.execute(stmt) or []
            print(f"{stmt}: " + ", ".join(str(list(r.values())[0]) for r in rows))
        except Exception as e:
            print(f"{stmt}: (failed: {short(e)})")
    local = local_counts(ROOT / "data" / "snapshot.duckdb")
    print(f"\n{'view':14} {'zetaris':>8} {'local':>8}")
    for v in VIEWS:
        try:
            z = list(b.query(f"SELECT COUNT(*) AS n FROM {v}")[0].values())[0]
        except Exception as e:
            z = f"ERR {short(e)[:60]}"
        match = z == local[v]
        ok &= match
        print(f"{v:14} {z!s:>8} {local[v]:>8}  {'OK' if match else 'MISMATCH'}")
    print("\nALL OK" if ok else "\nCHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("ERROR:", short(e), file=sys.stderr)
        sys.exit(1)
