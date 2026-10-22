import json
from pathlib import Path
from app.pipeline import run

INP = json.loads((Path(__file__).parents[1] / "input_examples" / "example_1.json").read_text())["input"]


def test_markovian_drives_rounds_with_carryover():
    mk = run(INP, "test-mk")["output"]["result"]["token_report"]["markovian"]
    assert mk["status"] == "completed" and mk["tokenLabel"] == "estimated"
    assert len(mk["chunks"]) == 2 and mk["chunks"][1]["carryover_chars"] > 0
    assert mk["chunkConfig"]["maxChunks"] == 3
