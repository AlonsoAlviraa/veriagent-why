"""Held-out report (docs/HELDOUT_RESULTS.md): paired per-item stats over repeats on bench/splits/holdout_v1.json.
usage: python -m bench.heldout_report bench/results/holdout [--md]
Arms are files tatqa-<tag>-<system>-r<k>.jsonl. Per item: majority vote of EM over repeats; paired exact McNemar on the majority
vectors; paired bootstrap 95% CI of the difference in per-item mean EM; mean±sd of EM across repeats; confidence metrics
(Brier, ECE 10 equal-width bins, AUROC, AURC) over all rows. agent_cr also reported with the train-fitted map (CR_USE_CALIB)."""
from __future__ import annotations
import json, math, random, re, statistics as st, sys
from collections import defaultdict
from pathlib import Path

import os
# split under analysis: HELDOUT_SPLIT=bench/splits/tatqa_test500_v1.json (default: the holdout_v1 pilot)
HOLD = Path(os.environ.get("HELDOUT_SPLIT") or Path(__file__).resolve().parent / "splits" / "holdout_v1.json")


def load(d: Path):
    ids = json.loads(HOLD.read_text())["ids"]
    arms = defaultdict(dict)
    for f in sorted(d.glob("tatqa-*-r*.jsonl")):
        m = re.match(r"tatqa-(.+)-r(\d+)\.jsonl", f.name)
        rows = {}
        for l in f.read_text().splitlines():
            r = json.loads(l)
            if not r.get("error") or r["id"] not in rows:
                rows[r["id"]] = r  # last good record per id
        arms[m.group(1)][int(m.group(2))] = rows
    return ids, arms


def em(r):
    return float(((r or {}).get("scores") or {}).get("em") or 0.0)


def mcnemar(a, b):
    n01 = sum(1 for x, y in zip(a, b) if not x and y); n10 = sum(1 for x, y in zip(a, b) if x and not y)
    n = n01 + n10
    if n == 0:
        return 1.0, n01, n10
    k = min(n01, n10)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n * 2
    return min(1.0, p), n01, n10


def boot_ci(a, b, B=10000, seed=2026):
    rng = random.Random(seed); n = len(a); d = [y - x for x, y in zip(a, b)]
    s = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return sum(d) / n, s[int(0.025 * B)], s[int(0.975 * B) - 1]


def auroc(y, s):
    P = [c for c, t in zip(s, y) if t]; N = [c for c, t in zip(s, y) if not t]
    if not P or not N:
        return None
    return sum((p > q) + 0.5 * (p == q) for p in P for q in N) / (len(P) * len(N))


def aurc(y, s):
    """Area under risk-coverage (lower is better); ties broken pessimistically-neutral by stable order."""
    order = sorted(range(len(y)), key=lambda i: -s[i]); err = 0; tot = 0.0
    for k, i in enumerate(order, 1):
        err += 0 if y[i] else 1; tot += err / k
    return tot / len(y)


def ece(y, s, bins=10):
    b = defaultdict(list)
    for t, c in zip(y, s):
        b[min(bins - 1, int(c * bins))].append((t, c))
    return sum(len(v) / len(y) * abs(sum(t for t, _ in v) / len(v) - sum(c for _, c in v) / len(v)) for v in b.values())


def conf_metrics(y, s):
    return {"n": len(y), "brier": round(sum((c - t) ** 2 for t, c in zip(y, s)) / len(y), 4), "ece": round(ece(y, s), 4),
            "auroc": None if auroc(y, s) is None else round(auroc(y, s), 4), "aurc": round(aurc(y, s), 4),
            "distinct": len(set(round(c, 3) for c in s)), "mean_conf": round(sum(s) / len(s), 3), "acc": round(sum(y) / len(y), 3)}


def calibrated(r):
    from .confidence import cr_tat
    from .fixes import isotonic_apply  # noqa: F401
    cmap = json.loads((Path(__file__).resolve().parent / "calib" / "cr_tatqa.json").read_text())["map"]
    i = dict(r["output"]["conf_inputs"]); i["cmap"] = cmap
    return cr_tat(**i)


def report(d: Path):
    ids, arms = load(d)
    out = {"holdout": {"file": HOLD.name, "n": len(ids), "ids_sha256": json.loads(HOLD.read_text())["ids_sha256"]}, "arms": {}, "paired": [], "confidence": {}}
    item = {}
    for arm, reps in sorted(arms.items()):
        per_rep = {k: [em(rows.get(i)) for i in ids] for k, rows in sorted(reps.items())}
        complete = {k: sum(1 for i in ids if i in reps[k] and not reps[k][i].get("error")) for k in reps}
        means = [sum(v) / len(v) for v in per_rep.values()]
        mat = list(zip(*per_rep.values()))
        maj = [1.0 if sum(x) > len(x) / 2 else 0.0 for x in mat]
        item[arm] = {"maj": maj, "mean": [sum(x) / len(x) for x in mat]}
        rows = [r for rs in reps.values() for r in rs.values() if not r.get("error")]
        calls = [r["meter"]["calls"] for r in rows]
        revs = sorted({(r.get("code_rev"), r.get("dirty")) for r in rows}, key=str)
        f1 = [float(r["scores"].get("f1") or 0) for r in rows]
        out["arms"][arm] = {"repeats": len(per_rep), "complete_per_repeat": complete, "em_per_repeat": [round(m, 3) for m in means],
                            "em_mean": round(st.mean(means), 3), "em_sd": round(st.stdev(means), 3) if len(means) > 1 else None,
                            "em_majority": round(sum(maj) / len(maj), 3), "f1_mean": round(sum(f1) / len(f1), 3),
                            "calls_per_item": round(sum(calls) / len(calls), 2), "code_rev_dirty": revs,
                            "items_unstable_across_repeats": sum(1 for x in mat if 0 < sum(x) < len(x))}
        y = [em(r) == 1.0 for r in rows]
        s = [float(r["output"].get("confidence") or 0) for r in rows]
        out["confidence"][arm + " (shipped)"] = conf_metrics(y, s)
        from .abstention import selective
        out.setdefault("abstention", {})[arm] = selective(rows, em)
        if arm.endswith("agent_cr"):
            out["confidence"][arm + " (train-fitted map, CR_USE_CALIB=1)"] = conf_metrics(y, [calibrated(r) for r in rows])
    names = sorted(item)
    base = next((a for a in names if a.startswith("base-")), None)
    pairs = [(base, a) for a in names if base and a != base] + [(a, b) for a in names for b in names if a < b and base not in (a, b)]
    for a, b in pairs:
        p, n01, n10 = mcnemar(item[a]["maj"], item[b]["maj"])
        dm, lo, hi = boot_ci(item[a]["mean"], item[b]["mean"])
        out["paired"].append({"a": a, "b": b, "delta_em_b_minus_a": round(dm, 3), "ci95": [round(lo, 3), round(hi, 3)],
                              "mcnemar_p": round(p, 4), "b_better": n01, "b_worse": n10})
    return out


def md(o):
    L = [f"Held-out `{o['holdout']['file']}` n={o['holdout']['n']} (ids sha256 `{o['holdout']['ids_sha256'][:16]}…`)", "",
         "| arm | repeats | EM per repeat | EM mean ± sd | EM majority | F1 mean | calls/item | unstable items | code_rev (dirty) |", "|---|---|---|---|---|---|---|---|---|"]
    for a, v in o["arms"].items():
        L.append(f"| {a} | {v['repeats']} | {v['em_per_repeat']} | {v['em_mean']} ± {v['em_sd']} | {v['em_majority']} | {v['f1_mean']} | {v['calls_per_item']} | {v['items_unstable_across_repeats']} | {', '.join(f'{r} ({d})' for r, d in v['code_rev_dirty'])} |")
    L += ["", "| A → B | ΔEM (B−A, per-item mean) | bootstrap 95% CI | McNemar p (majority) | B better / worse |", "|---|---|---|---|---|"]
    for p in o["paired"]:
        L.append(f"| {p['a']} → {p['b']} | {p['delta_em_b_minus_a']:+.3f} | [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] | {p['mcnemar_p']} | {p['b_better']} / {p['b_worse']} |")
    L += ["", "| confidence | n rows | acc | mean conf | distinct values | Brier ↓ | ECE ↓ | AUROC ↑ | AURC ↓ |", "|---|---|---|---|---|---|---|---|---|"]
    for a, c in o["confidence"].items():
        L.append(f"| {a} | {c['n']} | {c['acc']} | {c['mean_conf']} | {c['distinct']} | {c['brier']} | {c['ece']} | {c['auroc']} | {c['aurc']} |")
    if o.get("abstention"):
        L += ["", "| abstention (pre-registered: lex >= 0.809) | n | answered | coverage | selective EM | AURC ↓ |", "|---|---|---|---|---|---|"]
        for a, v in o["abstention"].items():
            L.append(f"| {a} | {v['n']} | {v['answered']} | {v['coverage']} | {v['selective_em']} | {v['aurc']} |")
    return "\n".join(L)


if __name__ == "__main__":
    o = report(Path(sys.argv[1]))
    print(md(o) if "--md" in sys.argv else json.dumps(o, indent=1))
