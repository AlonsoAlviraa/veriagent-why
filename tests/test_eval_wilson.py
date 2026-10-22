import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "eval"))
from eval import wilson


def test_wilson_known_values():
    lo, hi = wilson(9, 18)
    assert round(lo, 3) == 0.290 and round(hi, 3) == 0.710
    assert wilson(0, 0) == (0.0, 0.0)
