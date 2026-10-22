"""Zetaris adapter with two backends behind one interface:

- sample: local DuckDB snapshot built by scripts/make_data.py (same view names, same SQL).
- zetaris: Zetaris REST SQL endpoint (ZETARIS_REST_URL, ZETARIS_API_KEY). TODO: wire once a
  Zetaris instance is reachable (not available on Day 1; see README).
"""
from __future__ import annotations
import subprocess, sys
from ..config import ROOT, env, sample_mode

SNAPSHOT = ROOT / "data" / "snapshot.duckdb"


class SampleBackend:
    name = "sample-duckdb"

    def __init__(self):
        import duckdb
        if not SNAPSHOT.exists():
            subprocess.run([sys.executable, str(ROOT / "scripts" / "make_data.py")], check=True, capture_output=True)
        self.con = duckdb.connect(str(SNAPSHOT), read_only=True)

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        cur = self.con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


class ZetarisBackend:
    name = "zetaris"

    def __init__(self):
        if not env("ZETARIS_REST_URL"):
            raise RuntimeError("ZETARIS_REST_URL not set")

    def query(self, sql: str, params: list | None = None) -> list[dict]:  # pragma: no cover
        raise NotImplementedError("TODO: Zetaris REST SQL call (Day 2)")


def get_backend():
    if sample_mode() or env("ZETARIS_BACKEND", "sample") == "sample":
        return SampleBackend()
    return ZetarisBackend()
