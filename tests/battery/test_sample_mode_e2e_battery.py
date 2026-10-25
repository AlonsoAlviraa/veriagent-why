"""SAMPLE_MODE end-to-end: the 3 demo scenarios from a subprocess with no credentials reproduce the committed
output_examples/ exactly, except the 3 run-specific fields (trace_id, execution_time_seconds, wall_clock_s)."""
import json, os, subprocess, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
VOLATILE = {"trace_id", "execution_time_seconds", "wall_clock_s"}
EXPECT = {1: ("success", "carrier_sla_breach"), 2: ("success", "carrier_sla_breach"), 3: ("partial", None)}


def strip(d):
    if isinstance(d, dict):
        return {k: strip(v) for k, v in d.items() if k not in VOLATILE}
    if isinstance(d, list):
        return [strip(x) for x in d]
    return d


def run(i, tmp):
    env = {k: v for k, v in os.environ.items() if not any(s in k for s in ("API_KEY", "TOKEN", "SAMPLE_MODE", "ZETARIS", "NIGHTSHIFT"))}
    env["VA_LOG_DIR"] = str(tmp)
    p = subprocess.run([sys.executable, "run.py", "--input", f"input_examples/example_{i}.json"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-500:]
    return json.loads(p.stdout[p.stdout.index("{"):].replace(str(tmp), "logs")), p.stderr


@pytest.fixture(scope="module")
def outs(tmp_path_factory):
    return {(i, k): run(i, tmp_path_factory.mktemp(f"e{i}{k}")) for i in (1, 2, 3) for k in (0, 1)}


@pytest.mark.parametrize("i", [1, 2, 3])
def test_matches_committed_output_example(outs, i):
    ref = json.loads((ROOT / f"output_examples/example_{i}.json").read_text())
    assert strip(outs[(i, 0)][0]) == strip(ref)


@pytest.mark.parametrize("i", [1, 2, 3])
def test_rerun_identical(outs, i):
    assert strip(outs[(i, 0)][0]) == strip(outs[(i, 1)][0])


@pytest.mark.parametrize("i", [1, 2, 3])
def test_status_and_top_cause(outs, i):
    d = outs[(i, 0)][0]; st, cause = EXPECT[i]
    assert d["status"] == st
    if cause:
        assert d["output"]["result"]["analysis"]["top_cause_label"] == cause


@pytest.mark.parametrize("i", [1, 2, 3])
def test_sample_mode_is_announced(outs, i):
    assert "SAMPLE MODE" in outs[(i, 0)][1] or "SAMPLE MODE" in json.dumps(outs[(i, 0)][0])


@pytest.mark.parametrize("i", [1, 2, 3])
def test_no_secret_like_strings_in_output(outs, i):
    import re
    sys.path.insert(0, str(ROOT / "scripts")); import secret_scan as S
    txt = json.dumps(outs[(i, 0)][0]) + outs[(i, 0)][1]
    assert not [n for n, p in S.PATTERNS.items() if re.search(p, txt)]
