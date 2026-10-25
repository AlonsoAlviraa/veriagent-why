"""Shared fixtures for the generated test battery (docs/TEST_BATTERY_REPORT.md). Offline, no network, no spend."""
import subprocess, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def snap_path(tmp_path_factory):
    out = tmp_path_factory.mktemp("snap") / "snap.duckdb"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_data.py"), "--out", str(out)], check=True, capture_output=True)
    return out


@pytest.fixture(scope="session")
def snap(snap_path):
    from app.adapters.zetaris import SnapshotBackend
    db = SnapshotBackend(snap_path)
    yield db
    db.con.close()
