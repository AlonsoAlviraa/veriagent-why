import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_live_demo_script_snapshot_green_red_green():
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_live_demo.py"), "--backend", "snapshot"],
                       capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 0, p.stdout + p.stderr
    lines = [l for l in p.stdout.splitlines() if l.startswith("[")]
    assert [l.rsplit(" ", 1)[-1] for l in lines] == ["GREEN", "RED", "GREEN"]
