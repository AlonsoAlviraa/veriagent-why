"""Zetaris adapter with two backends behind one interface:

- sample: local DuckDB snapshot built by scripts/make_data.py (same view names, same SQL).
- zetaris: Zetaris REST SQL endpoint (ZETARIS_BACKEND=zetaris). Implemented from the public setup guide,
  NOT yet tested against a live instance.
"""
from __future__ import annotations
import subprocess, sys
from ..config import ROOT, env, sample_mode

SNAPSHOT = ROOT / "data" / "snapshot.duckdb"


class SampleBackend:
    name = "sample-duckdb"

    def __init__(self, dataset: str | None = None):
        import duckdb
        path = SNAPSHOT
        if dataset:
            if not dataset.replace("-", "").replace("_", "").isalnum():
                raise ValueError("invalid dataset id")
            path = ROOT / "data" / "eval" / f"{dataset}.duckdb"
            if not path.exists():
                raise ValueError(f"dataset {dataset} not built; run python eval/build_datasets.py")
        elif not path.exists():
            subprocess.run([sys.executable, str(ROOT / "scripts" / "make_data.py")], check=True, capture_output=True)
        self.con = duckdb.connect(str(path), read_only=True)

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        cur = self.con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


class ZetarisBackend:
    """Zetaris REST SQL backend. UNTESTED against a live instance (none reachable from the build box).

    Written from the hackathon Participant Setup Guide: POST {ZETARIS_REST_URL}/sql-editor/sqls/run with
    Authorization: Bearer <ZETARIS_API_KEY>, X-Org-ID, a fresh UUID X-Request-ID, and JSON
    {queryId, sql, source: "SqlEditor", limit}; rows come back under "data".
    Unknowns (TODO verify on a live instance via /redoc): the field carrying column names, and
    whether bind parameters exist (we inline escaped literals). View names get ZETARIS_VIEW_PREFIX.
    """
    name = "zetaris-rest (untested)"
    VIEWS = ("v_orders", "v_returns", "v_tickets", "v_logistics", "v_promotions")

    def __init__(self, dataset: str | None = None):
        self.url = env("ZETARIS_REST_URL")
        if not self.url or not env("ZETARIS_API_KEY") or not env("ZETARIS_ORG_ID"):
            raise RuntimeError("ZETARIS_REST_URL, ZETARIS_API_KEY and ZETARIS_ORG_ID must be set")
        self.prefix = env("ZETARIS_VIEW_PREFIX")

    @staticmethod
    def literal(v) -> str:
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return repr(v)
        return "'" + str(v).replace("'", "''") + "'"

    def render(self, sql: str, params: list | None) -> str:
        parts = sql.split("?")
        if len(parts) - 1 != len(params or []):
            raise ValueError("placeholder/parameter count mismatch")
        out = parts[0] + "".join(self.literal(p) + rest for p, rest in zip(params or [], parts[1:]))
        if self.prefix:
            import re
            out = re.sub(r"\b(" + "|".join(self.VIEWS) + r")\b", lambda m: self.prefix + m.group(1), out)
        return out

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        import json as _json, urllib.request, uuid
        from ..config import TIMEOUTS
        body = {"queryId": str(uuid.uuid4()), "sql": self.render(sql, params), "source": "SqlEditor", "limit": 100000}
        req = urllib.request.Request(self.url.rstrip("/") + "/sql-editor/sqls/run", data=_json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + env("ZETARIS_API_KEY"),
            "X-Org-ID": env("ZETARIS_ORG_ID"), "X-Request-ID": str(uuid.uuid4())})
        with urllib.request.urlopen(req, timeout=TIMEOUTS["zetaris_s"]) as r:
            out = _json.load(r)
        data = out.get("data") or []
        if data and isinstance(data[0], dict):
            return data
        cols = out.get("columns") or out.get("columnNames") or out.get("schema") or out.get("header")
        if cols and isinstance(cols[0], dict):
            cols = [c.get("name") for c in cols]
        if not cols:
            raise RuntimeError("Zetaris reply has no column names; TODO: confirm the response schema in /redoc")
        return [dict(zip(cols, row)) for row in data]


def get_backend(dataset: str | None = None):
    if sample_mode() or env("ZETARIS_BACKEND", "sample") == "sample":
        return SampleBackend(dataset)
    return ZetarisBackend(dataset)
