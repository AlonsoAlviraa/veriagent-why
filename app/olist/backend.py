"""Olist backends: DuckDB snapshot (data/olist/olist.duckdb, built by scripts/olist_fetch.py) or
Zetaris over JDBC (SchemaStore container `olist`, loaded by scripts/olist_zetaris_load.py)."""
from __future__ import annotations
from ..adapters.zetaris import SnapshotBackend, ZetarisJdbcBackend
from ..config import ROOT, env, sample_mode
from .metrics import TABLES

OLIST_DB = ROOT / "data" / "olist" / "olist.duckdb"


class OlistSnapshot(SnapshotBackend):
    name = "olist-snapshot-duckdb"

    def __init__(self, path=OLIST_DB, read_only: bool = True):
        from pathlib import Path
        if not Path(path).exists():
            raise RuntimeError(f"{path} missing: run python scripts/olist_fetch.py")
        super().__init__(path, read_only)


class OlistZetaris(ZetarisJdbcBackend):
    name = "olist-zetaris-jdbc"
    views = TABLES

    def __init__(self, conn=None):
        super().__init__(None, conn)
        self.prefix = env("OLIST_VIEW_PREFIX", "olist.")
        if self.prefix and not self.prefix.endswith("."):
            self.prefix += "."


def olist_backend():
    if sample_mode() or env("ZETARIS_BACKEND", "sample") == "sample":
        return OlistSnapshot()
    return OlistZetaris()
