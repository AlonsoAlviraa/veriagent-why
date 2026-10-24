"""Zetaris adapter with two backends behind one interface (`query(sql, params) -> list[dict]`):

- sample (default): local DuckDB snapshot built by scripts/make_data.py (same view names, same SQL).
- zetaris: Zetaris Lightning over JDBC (JayDeBeApi + JPype), ZETARIS_BACKEND=zetaris.
  Config: ZETARIS_JDBC_URL, ZETARIS_USER, ZETARIS_PASSWORD, ZETARIS_JDBC_JAR (path to the driver jar,
  kept OUTSIDE the repo). Follows the official getting-started guidance: driver class
  com.zetaris.lightning.jdbc.LightningDriver, one statement per call, verify with SELECT 1.
  View names get ZETARIS_VIEW_PREFIX (default "veriagent." = the SchemaStore container that
  scripts/zetaris_load.py creates).
"""
from __future__ import annotations
import re, subprocess, sys
from ..config import ROOT, env, sample_mode

SNAPSHOT = ROOT / "data" / "snapshot.duckdb"
VIEWS = ("v_orders", "v_returns", "v_tickets", "v_logistics", "v_promotions")
DRIVER_CLASS = "com.zetaris.lightning.jdbc.LightningDriver"
DEFAULT_JDBC_URL = "jdbc:zetaris:lightning@localhost:10000"


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


def literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"  # Spark SQL string literal


def render(sql: str, params: list | None, prefix: str = "") -> str:
    """Inline escaped literals (one plain statement per call), translate DuckDB-isms to Lightning
    (Spark) SQL and qualify the 5 view names."""
    parts = sql.split("?")
    if len(parts) - 1 != len(params or []):
        raise ValueError("placeholder/parameter count mismatch")
    out = parts[0] + "".join(literal(p) + rest for p, rest in zip(params or [], parts[1:]))
    out = re.sub(r"\bAS\s+VARCHAR\b", "AS STRING", out, flags=re.I)
    if prefix:
        out = re.sub(r"(?<![\w.])(" + "|".join(VIEWS) + r")\b", lambda m: prefix + m.group(1), out)
    return out.strip().rstrip(";")


def _py(v):
    """JDBC values -> plain Python (JPype may hand back java.lang.* objects)."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    s = str(v)
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            pass
    return s


def jdbc_connect():
    """Open a JayDeBeApi connection from env. Never logs the password."""
    jar, user, pw = env("ZETARIS_JDBC_JAR"), env("ZETARIS_USER"), env("ZETARIS_PASSWORD")
    url = env("ZETARIS_JDBC_URL", DEFAULT_JDBC_URL)
    missing = [k for k, v in (("ZETARIS_JDBC_JAR", jar), ("ZETARIS_USER", user), ("ZETARIS_PASSWORD", pw)) if not v]
    if missing:
        raise RuntimeError("missing env: " + ", ".join(missing))
    from pathlib import Path
    if not Path(jar).is_file():
        raise RuntimeError(f"ZETARIS_JDBC_JAR not found: {jar}")
    if Path(jar).resolve().is_relative_to(ROOT.resolve()):
        raise RuntimeError("keep the Zetaris JDBC jar outside the repo")
    import jaydebeapi
    return jaydebeapi.connect(DRIVER_CLASS, url, [user, pw], jar)


class ZetarisJdbcBackend:
    name = "zetaris-jdbc"

    def __init__(self, dataset: str | None = None, conn=None):
        if dataset:
            raise ValueError("eval datasets are local snapshots; the Zetaris backend serves the loaded demo data")
        self.prefix = env("ZETARIS_VIEW_PREFIX", "veriagent.")
        if self.prefix and not self.prefix.endswith("."):
            self.prefix += "."
        self.conn = conn or jdbc_connect()

    def execute(self, sql: str) -> list[dict] | None:
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            if not cur.description:
                return None
            cols = [d[0].split(".")[-1].lower() for d in cur.description]
            return [dict(zip(cols, map(_py, r))) for r in cur.fetchall()]
        finally:
            cur.close()

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        return self.execute(render(sql, params, self.prefix)) or []


class SnapshotBackend(SampleBackend):
    """DuckDB snapshot at an explicit path (same 5 views as the demo/Zetaris schema). Used by the
    public SAMPLE_MODE Space and by the CI mutation test (writable copy)."""
    name = "snapshot-duckdb"

    def __init__(self, path, read_only: bool = True):
        import duckdb
        self.path = str(path)
        self.con = duckdb.connect(self.path, read_only=read_only)


def badge(db) -> str:
    """Backend badge shown on every receipt: 'zetaris' only when the query really went over JDBC."""
    return "zetaris" if isinstance(db, ZetarisJdbcBackend) else "snapshot"


def schema(db) -> dict[str, list[str]]:
    """View -> column names, by querying each view (works for DuckDB and Zetaris)."""
    out = {}
    for v in VIEWS:
        r = db.query(f"SELECT * FROM {v} LIMIT 1")
        out[v] = sorted(r[0].keys()) if r else []
    return out


def get_backend(dataset: str | None = None):
    if sample_mode() or env("ZETARIS_BACKEND", "sample") == "sample":
        return SampleBackend(dataset)
    return ZetarisJdbcBackend(dataset)
