"""V11 fresh benchmark (docs/V11_PREREG.md): TableBench (Wu et al., AAAI 2025; HF Multilingual-Multimodal-NLP/TableBench,
Apache-2.0), file TableBench.jsonl at HF revision a23c244f9ccae1ea238d614fe7620984707e411a, sha256 ebcc6fce...79e.
Built and fingerprinted BEFORE any model call. No model calls here.
Kept: every item whose gold answer is a single number (optionally with % or $), excluding qsubtype TrendForecasting
(forecasts are not grounded in the table). Duplicate source ids keep the first occurrence (1 exact duplicate). No sub-sampling: all eligible items are used (no seed choice to tune).
Output: TAT-QA-format dataset (one document per question, table only, no paragraphs) + split file with ids + fingerprint.
Usage: python -m bench.v11_build /workspace/v11/TableBench.jsonl"""
from __future__ import annotations
import ast, hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DS, OUT, NAME = ROOT / "data/bench/tatqa", ROOT / "docs/v11", "v11_tablebench"
SRC_SHA = "ebcc6fcea565c9c0a51ecf1c72be58b3b7db7e9466a6a9581d0dc882cc72279e"
NUM = re.compile(r"-?\d[\d,]*\.?\d*%?|-?\.\d+%?")
EXCLUDE = {"TrendForecasting"}


def build(src: Path):
    raw = src.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SRC_SHA, "source file differs from the pre-registered one"
    docs, drop, seen = [], {"non_numeric": 0, "excluded_subtype": 0, "duplicate_id": 0}, set()
    for line in raw.decode().splitlines():
        x = json.loads(line)
        if x["id"] in seen: drop["duplicate_id"] += 1; continue
        seen.add(x["id"])
        a = str(x["answer"]).strip().replace("$", "").strip()
        if x["qsubtype"] in EXCLUDE: drop["excluded_subtype"] += 1; continue
        if not NUM.fullmatch(a): drop["non_numeric"] += 1; continue
        pct = a.endswith("%"); v = float(a.rstrip("%").replace(",", ""))
        t = x["table"] if isinstance(x["table"], dict) else ast.literal_eval(x["table"])
        grid = [[str(c) for c in t["columns"]]] + [[str(c) for c in r] for r in t["data"]]
        uid = "v11tb-" + x["id"][:16]
        docs.append({"table": {"uid": uid + "-t", "table": grid}, "paragraphs": [],
                     "questions": [{"uid": uid, "order": 1, "question": x["question"], "answer": v, "derivation": "",
                                    "answer_type": "arithmetic", "answer_from": "table", "rel_paragraphs": [],
                                    "req_comparison": False, "scale": "percent" if pct else ""}],
                     "source": {"tablebench_id": x["id"], "qtype": x["qtype"], "qsubtype": x["qsubtype"], "stated_answer": str(x["answer"])}})
    docs.sort(key=lambda d: d["questions"][0]["uid"])
    DS.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(docs, ensure_ascii=False, indent=0)
    (DS / f"tatqa_dataset_{NAME}.json").write_text(blob); (OUT / f"tatqa_dataset_{NAME}.json").write_text(blob)
    ids = [d["questions"][0]["uid"] for d in docs]
    fp = {"dataset_sha256": hashlib.sha256(blob.encode()).hexdigest(),
          "ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(), "source_sha256": SRC_SHA}
    split = {"name": NAME, "tatqa_split": NAME, "n": len(ids), "dropped": drop, **fp, "ids": ids}
    sp = OUT / f"split_{NAME}.json"; sp.write_text(json.dumps(split, indent=0))
    fp["split_sha256"] = hashlib.sha256(sp.read_bytes()).hexdigest()
    from collections import Counter
    print(json.dumps({"n": len(ids), "dropped": drop, **fp,
                      "by_subtype": Counter(d["source"]["qsubtype"] for d in docs)}, indent=1))


if __name__ == "__main__":
    build(Path(sys.argv[1]))
