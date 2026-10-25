"""Planted traps for the TAT-QA Claim Gate (bench.tatqa.gate) on real TAT-QA dev documents (development set).

Control: the official gold derivation + gold answer + a real table row as evidence (should pass).
Traps:   one operand in the gold derivation changed by 7-30%; the answer changed by 5-30% (expression kept);
         evidence quote with a fabricated number; a numeric answer with no expression that is not derivable.
Offline. Prints detection / false-alarm rates with Wilson 95% CIs.

    python scripts/tatqa_gate_traps.py [--dataset data/bench/tatqa/tatqa_dataset_dev.json] [--out docs/test_battery/tatqa_gate_traps.json]
"""
import argparse, json, random, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from bench.tatqa import context, gate, nums, safe_eval  # noqa: E402
from planted_traps import wilson  # noqa: E402

NUMRE = re.compile(r"\d[\d,]*\.?\d*")


def items(path, r):
    for doc in json.loads(Path(path).read_text()):
        ctx = context(doc)
        for q in doc["questions"]:
            if q.get("answer_type") != "arithmetic" or not q.get("derivation"):
                continue
            try:
                val = safe_eval(q["derivation"])
            except Exception:
                continue
            row = next((" | ".join(c for c in rw if c) for rw in doc["table"]["table"] if any(NUMRE.search(c) for c in rw[1:])), None)
            yield q["uid"], ctx, q["derivation"], val, q["answer"], row


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--dataset", default=str(ROOT / "data/bench/tatqa/tatqa_dataset_dev.json"))
    ap.add_argument("--out", default=str(ROOT / "docs/test_battery/tatqa_gate_traps.json")); ap.add_argument("--seed", type=int, default=20261025)
    a = ap.parse_args(argv); r = random.Random(a.seed); res = defaultdict(Counter); ex = defaultdict(list)

    def rec(kind, t, uid, reasons):
        k = "flagged" if reasons else "passed"; res[(kind, t)][k] += 1
        if (kind == "control") == bool(reasons) and len(ex[(kind, t)]) < 5:
            ex[(kind, t)].append({"uid": uid, "reasons": reasons[:2]})

    n = 0
    for uid, ctx, der, val, ans, row in items(a.dataset, r):
        n += 1
        out = {"answer": str(ans), "expression": der, "evidence": [row] if row else []}
        rec("control", "gold_derivation", uid, gate(out, ctx))
        ops = list(NUMRE.finditer(der))
        if ops:
            m = r.choice(ops); x = float(m.group().replace(",", "").rstrip("."))
            if x not in (0, 100, 1000) and x > 10:
                f = r.choice([1, -1]) * r.uniform(0.07, 0.3); y = round(x * (1 + f), 2)
                d2 = der[:m.start()] + f"{y:g}" + der[m.end():]
                try:
                    v2 = safe_eval(d2)
                    rec("trap", "operand_changed", uid, gate({"answer": f"{round(v2, 2)}", "expression": d2, "evidence": []}, ctx))
                except Exception:
                    pass
        if abs(val) > 0.5:
            bad = val * (1 + r.choice([1, -1]) * r.uniform(0.05, 0.3))
            rec("trap", "answer_not_expression_value", uid, gate({"answer": f"{round(bad, 2)}", "expression": der, "evidence": []}, ctx))
        if row:
            nm = list(NUMRE.finditer(row))
            if nm:
                m = nm[-1]; x = float(m.group().replace(",", "").rstrip(".") or 0)
                fake = row[:m.start()] + f"{x * 1.37 + 11:.0f}" + row[m.end():]
                rec("trap", "fabricated_evidence_number", uid, gate({"answer": str(ans), "expression": der, "evidence": [fake]}, ctx))
        if abs(val) > 1:
            weird = round(abs(val) * 7.31 + 913.17, 2)
            rec("trap", "untraceable_answer_no_expression", uid, gate({"answer": f"{weird}", "expression": "", "evidence": []}, ctx))
    rep = {"dataset": Path(a.dataset).name, "n_questions": n}
    for kind in ("trap", "control"):
        f = sum(c["flagged"] for (k, _), c in res.items() if k == kind); m = sum(sum(c.values()) for (k, _), c in res.items() if k == kind)
        rep[f"{kind}_flagged"] = [f, m, round(f / m, 4), wilson(f, m)]
    rep["by_type"] = {f"{k}/{t}": {**dict(c), "n": sum(c.values()), "rate_flagged": round(c["flagged"] / sum(c.values()), 4),
                                   "ci95": wilson(c["flagged"], sum(c.values()))} for (k, t), c in sorted(res.items())}
    rep["examples_wrong"] = {f"{k}/{t}": v for (k, t), v in ex.items()}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: v for k, v in rep.items() if k != "examples_wrong"}, indent=1))


if __name__ == "__main__":
    main()
