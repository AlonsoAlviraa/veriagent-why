"""Builds one seeded synthetic DuckDB per question into data/eval/ (gitignored)."""
import json, sys
from pathlib import Path
R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / "scripts"))
import make_data

files = ["questions.json"] + (["questions_test_v2.json"] if "--v2" in sys.argv else [])
for q in [q for f in files for q in json.loads((R / "eval" / f).read_text())]:
    make_data.write_duckdb(make_data.generate(q["seed"], q["scenario"]), R / "data" / "eval" / f"{q['qid']}.duckdb")
print("built")
