"""V9 slices (docs/V9_PREREG.md). TAT-QA dev is fully burned (0-1667 used by V7 fit/V7.1/V8), so V9 uses TAT-QA TRAIN.
Excluded: every question id that appears ANYWHERE in this repo's committed files (calibration samples, splits, features),
plus test500 / test_gold. Slices are disjoint BY TABLE (document), so no table is shared between design and hold-out.
Usage: python -m bench.v9_slices  -> writes docs/v9/design.json, docs/v9/holdout.json (ids only; no results read)."""
from __future__ import annotations
import hashlib, json, random, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED, N_DESIGN, N_HOLD = 9009, 600, 400
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def used_ids() -> set[str]:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    s: set[str] = set()
    for f in files:
        p = ROOT / f
        if p.suffix in (".json", ".jsonl", ".py", ".md", ".txt", ".csv") and p.is_file() and not f.startswith("docs/v9/"):
            s |= set(UUID.findall(p.read_text(errors="ignore")))
    s |= set(json.load(open(ROOT / "docs/v9/excluded_extra.json"))["ids"])  # box-only earlier battery runs
    return s


def build():
    train = json.load(open(ROOT / "data/bench/tatqa/tatqa_dataset_train.json"))
    used = used_ids()
    docs = [(d["table"]["uid"], [q["uid"] for q in d["questions"] if q["uid"] not in used]) for d in train]
    docs = [(u, qs) for u, qs in docs if qs and u not in used]
    random.Random(SEED).shuffle(docs)
    design, hold = [], []
    for u, qs in docs:
        if len(design) < N_DESIGN:
            design += qs
        elif len(hold) < N_HOLD:
            hold += qs
        else:
            break
    design, hold = design[:N_DESIGN], hold[:N_HOLD]
    assert not set(design) & set(hold) and not (set(design) | set(hold)) & used
    out = {}
    for name, ids in (("design", design), ("holdout", hold)):
        d = {"name": f"v9_{name}", "tatqa_split": "train", "seed": SEED,
             "source": "TAT-QA train, tables shuffled with seed 9009, ids appearing in any committed repo file excluded, table-disjoint",
             "ids": ids}
        p = ROOT / "docs/v9" / f"{name}.json"
        p.write_text(json.dumps(d, indent=0))
        out[name] = (len(ids), hashlib.sha256(p.read_bytes()).hexdigest())
    out["n_train_questions"] = sum(len(d["questions"]) for d in train)
    out["n_excluded_used"] = len(used)
    return out


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
