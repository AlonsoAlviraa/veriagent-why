"""Planted-trap run (scripts/planted_traps.py) as a test, plus pinned known limits of check_narrative.
The xfail(strict=True) cases document current behaviour that needs a product decision (docs/TEST_BATTERY_REPORT.md);
if someone fixes them, the strict xfail turns into a failure so the report gets updated."""
import json, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def rep(tmp_path_factory):
    import planted_traps
    out = tmp_path_factory.mktemp("pt") / "r.json"
    planted_traps.main(["--n", "300", "--seed", "7", "--out", str(out)])
    return json.loads(out.read_text())


def test_structured_traps_all_red(rep):
    assert rep["detection_red"][0] == rep["n_traps"] == 150


def test_structured_controls_all_green(rep):
    assert rep["controls_not_green"][0] == 0


def test_every_trap_type_present(rep):
    import planted_traps
    assert {k.split("/")[1] for k in rep["by_type"] if k.startswith("trap/")} == set(planted_traps.TRAPS)


def test_deterministic_for_seed(rep, tmp_path):
    import planted_traps
    planted_traps.main(["--n", "300", "--seed", "7", "--out", str(tmp_path / "b.json")])
    b = json.loads((tmp_path / "b.json").read_text())
    assert b["by_type"] == rep["by_type"] and b["narrative"] == rep["narrative"]


from app.checks.claims import check_narrative  # noqa: E402
F = ["on_time_rate 87.25 late_count 1234"]


@pytest.mark.parametrize("txt", ["On-time was 87.3%.", "Late was 1234.", "87.2", "87.25 and 1234"])
def test_narrative_supported_numbers_pass(txt):
    assert check_narrative(txt, F)["passed"]


@pytest.mark.parametrize("txt", ["On-time was 88.25%.", "Late was 1243.", "Late was 3,234."])
def test_narrative_wrong_numbers_flagged(txt):
    assert not check_narrative(txt, F)["passed"]


@pytest.mark.xfail(strict=True, reason="DECISION: thousands separator '1,234' is split into 1 and 234 -> false alarm")
def test_narrative_thousands_separator_supported():
    assert check_narrative("Late was 1,234.", F)["passed"]


@pytest.mark.xfail(strict=True, reason="DECISION: years and dates in prose are treated as unsupported numbers -> false alarm")
@pytest.mark.parametrize("txt", ["In 2026 on-time was 87.25.", "On Sep 15 on-time was 87.25."])
def test_narrative_dates_ignored(txt):
    assert check_narrative(txt, F)["passed"]


@pytest.mark.xfail(strict=True, reason="DECISION: spelled-out numbers are not checked -> missed trap")
def test_narrative_spelled_out_wrong_number_flagged():
    assert not check_narrative("Roughly one thousand shipments were late.", F)["passed"]
