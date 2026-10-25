"""bench/run.py writes one audit trace per item (on by default, --no-trace off), valid against the schema, no secrets."""
import gzip, json
from pathlib import Path
from bench import run

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "docs" / "audit_trace.schema.json").read_text(encoding="utf-8"))
TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool, "null": type(None)}


def _valid(obj, sch):
    """Minimal JSON-Schema check (type / required / properties / items) so the test never skips."""
    if "$ref" in sch:
        node = SCHEMA
        for part in sch["$ref"].lstrip("#/").split("/"):
            node = node[part]
        sch = node
    t = sch.get("type")
    if t:
        ts = t if isinstance(t, list) else [t]
        assert isinstance(obj, tuple(TYPES[x] for x in ts)), (obj if not isinstance(obj, (dict, list)) else type(obj), t)
    if isinstance(obj, dict):
        for k in sch.get("required", []):
            assert k in obj, k
        for k, s in (sch.get("properties") or {}).items():
            if k in obj:
                _valid(obj[k], s)
    if isinstance(obj, list) and isinstance(sch.get("items"), dict):
        for x in obj:
            _valid(x, sch["items"])


def _run(tmp_path, bench, systems, extra=()):
    out = tmp_path / f"{bench}-t.jsonl"
    run.main(["--bench", bench, "--systems", systems, "--offline", "--fixtures", "--out", str(out),
              "--trace-dir", str(tmp_path / "traces"), *extra])
    return out, [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]


def test_one_trace_per_item_and_schema(tmp_path):
    for bench, systems in (("tatqa", "agent,agent_mk"), ("insightbench", "agent")):
        out, rows = _run(tmp_path, bench, systems)
        idx = [json.loads(l) for l in (tmp_path / "traces" / out.stem / "audit_index.jsonl").read_text(encoding="utf-8").splitlines()]
        assert rows and len(idx) == len(rows) and {(i["config"], i["id"]) for i in idx} == {(r["system"], r["id"]) for r in rows}
        for i in idx:
            assert set(i) >= {"id", "config", "score", "failure_cause", "path"}
            t = json.loads(Path(i["path"]).read_text(encoding="utf-8"))
            _valid(t, SCHEMA)
        for r in rows:  # full prompts never land in the results row
            assert all("prompt_full" not in c for c in (r.get("meter") or {}).get("trace_calls") or [])


def test_no_trace_flag(tmp_path):
    _run(tmp_path, "tatqa", "agent", ["--no-trace"])
    assert not (tmp_path / "traces").exists()


def test_redaction_in_item_trace_and_gzip(tmp_path):
    from bench.audit_trace import write_item_trace
    key = "nvapi-" + "A" * 30
    row = {"bench": "tatqa", "system": "agent", "id": "x1", "model": "m", "scores": {"em": 0}, "gold": {"answer": "1", "scale": ""},
           "output": {"answer": "Bearer " + "b" * 20, "evidence": [key]},
           "meter": {"calls": 1, "trace_calls": [{"i": 1, "tag": "tat_agent", "prompt": "k=" + key, "prompt_full": "full " + key}]}}
    i = write_item_trace(row, tmp_path / "r.jsonl", Path("data/bench"), tmp_path / "tr", min_free_gb=0)
    txt = Path(i["path"]).read_text(encoding="utf-8")
    assert key not in txt and "b" * 20 not in txt and i["redactions"]
    with gzip.open(i["prompts_gz"], "rt") as f:
        assert key not in f.read()
