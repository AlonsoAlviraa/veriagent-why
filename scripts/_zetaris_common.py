"""Shared helpers for scripts/zetaris_load.py and scripts/zetaris_check.py (stdlib + app)."""
from __future__ import annotations
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


from app.config import load_dotenv  # noqa: E402,F401


def local_counts(snapshot: Path) -> dict[str, int]:
    import duckdb
    from app.adapters.zetaris import VIEWS
    con = duckdb.connect(str(snapshot), read_only=True)
    return {v: con.execute(f"SELECT COUNT(*) FROM {v}").fetchone()[0] for v in VIEWS}


def short(e: Exception) -> str:
    s = str(e).splitlines()[0] if str(e) else type(e).__name__
    return s[:300]
