"""Download public benchmark data into data/bench/ (gitignored). No login, pinned commits, cached.

    python -m bench.download insightbench [--limit N]
    python -m bench.download tatqa
    python -m bench.download all

Sources (pinned):
- InsightBench: github.com/ServiceNow/insight-bench @ IB_COMMIT, data/notebooks/flag-*.json + csvs
  (repo code: MIT; HF card ServiceNow/insight_bench: CC-BY-4.0; the paper's dataset table lists
  CC BY-NC 4.0 -> we treat it as non-commercial research use, see docs/BENCHMARKS.md).
- TAT-QA: github.com/NExTplusplus/TAT-QA @ TAT_COMMIT, dataset_raw/tatqa_dataset_dev.json (CC BY 4.0)
  plus the official scorer files tatqa_eval.py / tatqa_metric.py / tatqa_utils.py (MIT), fetched,
  not vendored.
A MANIFEST.json with sha256 of every file is written next to the data.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "bench"
IB_COMMIT = "33c27c1282cb7ed73267d36fb84e27b6ea8aac2b"
TAT_COMMIT = "870accc41953dcde885aabeb963d94aabdc0fbc3"
IB_RAW = f"https://raw.githubusercontent.com/ServiceNow/insight-bench/{IB_COMMIT}/"
TAT_RAW = f"https://raw.githubusercontent.com/NExTplusplus/TAT-QA/{TAT_COMMIT}/"
IB_LIST = "https://huggingface.co/api/datasets/ServiceNow/insight_bench/tree/main/json"  # names only; files come from the pinned GitHub commit


def fetch(url: str, dest: Path, retries: int = 3) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for a in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return dest
        except Exception as e:
            if a == retries - 1:
                raise RuntimeError(f"download failed: {url}: {e}")
            time.sleep(2 * (a + 1))


def _manifest(d: Path, meta: dict) -> None:
    files = {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(d.rglob("*")) if p.is_file() and p.name != "MANIFEST.json"}
    (d / "MANIFEST.json").write_text(json.dumps({**meta, "files": files}, indent=1))


def insightbench(limit: int | None = None) -> Path:
    d = DATA / "insightbench"
    with urllib.request.urlopen(IB_LIST, timeout=60) as r:
        names = [t["path"].split("/")[-1] for t in json.load(r)]
    tasks = sorted(("data/notebooks/" + n for n in names if n.startswith("flag-") and n.endswith(".json")),
                   key=lambda p: int(p.rsplit("-", 1)[1].split(".")[0]))
    if limit:
        tasks = tasks[:limit]
    for p in tasks:
        task = json.loads(fetch(IB_RAW + p, d / p).read_text())
        for k in ("dataset_csv_path", "user_dataset_csv_path"):
            if task.get(k):
                fetch(IB_RAW + task[k], d / task[k])
    _manifest(d, {"source": "ServiceNow/insight-bench", "commit": IB_COMMIT, "tasks": len(tasks),
                  "license": "repo MIT; data CC-BY-4.0 (HF card) / CC BY-NC 4.0 (paper) - declared both"})
    print(f"insightbench: {len(tasks)} tasks -> {d}")
    return d


def tatqa() -> Path:
    d = DATA / "tatqa"
    for f in ("dataset_raw/tatqa_dataset_dev.json", "dataset_raw/tatqa_dataset_test_gold.json", "tatqa_eval.py", "tatqa_metric.py", "tatqa_utils.py", "LICENSE"):
        fetch(TAT_RAW + f, d / Path(f).name)
    _manifest(d, {"source": "NExTplusplus/TAT-QA", "commit": TAT_COMMIT, "license": "data CC BY 4.0; code MIT"})
    print(f"tatqa: dev + official scorer -> {d}")
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["insightbench", "tatqa", "all"])
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.which in ("insightbench", "all"):
        insightbench(a.limit)
    if a.which in ("tatqa", "all"):
        tatqa()
    sys.exit(0)
