import subprocess, sys
from pathlib import Path

S = Path(__file__).parents[1] / "scripts" / "nvidia_smoke.py"


def test_skips_cleanly_without_key():
    env = {"PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(S)], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.startswith("SKIP")


def test_never_prints_key_on_failure():
    env = {"PATH": "/usr/bin:/bin", "NVIDIA_API_KEY": "dummy-value-123", "NVIDIA_BASE_URL": "http://127.0.0.1:9/v1"}
    r = subprocess.run([sys.executable, str(S)], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 1 and "dummy-value-123" not in r.stdout + r.stderr
