"""Choose the V7 abstention signal, threshold and operating point using ONLY TAT-QA train/dev rows.

Refuses any row whose id is in the official TAT-QA test_gold, test500 or holdout_v1 (pilot).
No model calls ($0): it reads existing result rows.

Pre-declared rule (written before computing any AURC or risk; only the value ranges of the fields were inspected):
- Candidate signals, all available at answer time for agent_mk with the critic/calibration OFF:
  conf_raw (model self-reported confidence), conf_det (deterministic gate/trace confidence),
  lex = conf_det first, conf_raw as tie-break (conf_det + conf_raw/100). Missing values -> 0.
- Signal = lowest AURC on the pooled train+dev rows.
- Operating point = answer iff signal >= t, where t minimises selective risk (1-EM on answered)
  subject to coverage >= 0.80; ties -> higher coverage.

Usage: python -m bench.abstention_fit --train <jsonl> --dev <jsonl> --tatqa-dir data/bench/tatqa --out bench/calib/abstention_v7.json
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_COVERAGE = 0.80


def _uids(p):
    return {q["uid"] for t in json.loads(Path(p).read_text()) for q in t["questions"]}


def signals(o: dict) -> dict:
    raw = o.get("confidence"); det = o.get("confidence_det")
    raw = float(raw) if isinstance(raw, (int, float)) else 0.0
    det = float(det) if isinstance(det, (int, float)) else 0.0
    return {"conf_raw": raw, "conf_det": det, "lex": det + raw / 100}


def aurc(pairs):
    """pairs: (signal, correct). Mean selective risk over coverage k=1..n, sorted by signal desc
    (ties broken pessimistically: wrong answers first)."""
    s = sorted(pairs, key=lambda x: (-x[0], x[1]))
    err, tot = 0, 0.0
    for k, (_, c) in enumerate(s, 1):
        err += 1 - c; tot += err / k
    return tot / len(s)


def op_point(pairs, min_cov=MIN_COVERAGE):
    n, best = len(pairs), None
    for t in sorted({p[0] for p in pairs}):
        ans = [c for v, c in pairs if v >= t]
        cov = len(ans) / n
        if cov < min_cov or not ans:
            continue
        risk = 1 - sum(ans) / len(ans)
        key = (round(risk, 12), -cov)
        if best is None or key < best[0]:
            best = (key, {"threshold": t, "coverage": round(cov, 4), "selective_risk": round(risk, 4),
                          "selective_em": round(1 - risk, 4), "answered": len(ans), "n": n})
    return best[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True); ap.add_argument("--dev", required=True)
    ap.add_argument("--tatqa-dir", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    d = Path(a.tatqa_dir)
    train_u, dev_u, test_u = (_uids(d / f"tatqa_dataset_{s}.json") for s in ("train", "dev", "test_gold"))
    t500 = json.loads((ROOT / "bench/splits/tatqa_test500_v1.json").read_text())
    ho = json.loads((ROOT / "bench/splits/holdout_v1.json").read_text())
    forbidden = test_u | set(t500.get("ids", [])) | set(ho.get("ids", []) or ho.get("tatqa", []) or [])
    rows = {}
    for split, path, allowed in (("train", a.train, train_u), ("dev", a.dev, dev_u)):
        rs = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
        rs = [r for r in rs if r.get("bench") == "tatqa"]
        bad = [r["id"] for r in rs if r["id"] in forbidden or r["id"] not in allowed]
        if bad:
            raise SystemExit(f"{path}: {len(bad)} ids not in TAT-QA {split} or in a forbidden split; refusing")
        rows[split] = [(signals(r["output"]), float(r["scores"]["em"])) for r in rs]
    pooled = rows["train"] + rows["dev"]
    names = ["conf_raw", "conf_det", "lex"]
    table = {nm: {sp: round(aurc([(s[nm], c) for s, c in rows[sp]]), 4) for sp in ("train", "dev")} |
             {"pooled": round(aurc([(s[nm], c) for s, c in pooled]), 4)} for nm in names}
    sig = min(names, key=lambda nm: (table[nm]["pooled"], names.index(nm)))
    op = op_point([(s[sig], c) for s, c in pooled])
    per = {sp: op_point([(s[sig], c) for s, c in rows[sp]], 0.0) for sp in ("train", "dev")}
    for sp in ("train", "dev"):  # what the pooled threshold gives on each split
        prs = [(s[sig], c) for s, c in rows[sp]]; ans = [c for v, c in prs if v >= op["threshold"]]
        per[sp] = {"coverage": round(len(ans) / len(prs), 4), "selective_em": round(sum(ans) / len(ans), 4),
                   "full_em": round(sum(c for _, c in prs) / len(prs), 4), "n": len(prs)}
    out = {"rule": __doc__.split("Pre-declared rule")[1].split("Usage")[0].strip(),
           "inputs": {sp: {"file": Path(p).name, "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
                      for sp, p in (("train", a.train), ("dev", a.dev))},
           "aurc": table, "signal": sig, "operating_point": op, "per_split_at_threshold": per}
    Path(a.out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
