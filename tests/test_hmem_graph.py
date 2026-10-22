import json
from pathlib import Path
from app.pipeline import run

ROOT = Path(__file__).parents[1]
INP = json.loads((ROOT / "input_examples" / "example_1.json").read_text())["input"]


def test_ledger_is_meterless_and_every_hypothesis_verdict_is_an_edge():
    r = run(INP, "test-hmem")["output"]["result"]
    assert r["evidence_graph"]["backend"].startswith("meterless-hmem")
    entries = [json.loads(l) for l in (ROOT / r["evidence_graph"]["hmem_ledger_file"]).read_text().splitlines()]
    edges = [e for e in entries if "edge" in e["newState"]["tags"]]
    top = r["analysis"]["top_cause"]["hyp"]
    sup = [e for e in edges if "supports" in e["newState"]["tags"] and top in e["newState"]["content"]]
    assert sup and all(len(e["newState"].get("derivedFrom") or []) == 2 for e in sup)
    assert all(c["row_ids"] for c in r["claims"])


def test_sample_mode_is_deterministic():
    a = run(INP, "det-a")["output"]["result"]; b = run(INP, "det-b")["output"]["result"]
    strip = lambda m: m.split("\n", 1)[1]
    assert strip(a["memo_md"]) == strip(b["memo_md"]) and a["confidence"] == b["confidence"]
