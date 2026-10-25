"""V11 analysis (docs/V11_PREREG.md), frozen and committed BEFORE any model call on the V11 set.
Systems from one run: agent_v9 rows give the V7 answer (+ V9 features); rag rows give plain RAG. The V9_full decision is
recomputed with the frozen app/v9conf.row_decision (lambda 0.683, never refit). Trivial rule = median of all numeric
table cells (zero model calls). Errored rows count as wrong; for V7+V9 they count as abstentions (no answer emitted).
Usage: python -m bench.v11_analysis "<runs glob>" > docs/v11/results_v11.json"""
from __future__ import annotations
import glob, json, random, statistics, sys
from app.v9conf import row_decision
from bench.v9_final import score
from bench.v9_gen_analysis import AU

DATA = "docs/v11/tatqa_dataset_v11_tablebench.json"; SPLIT = "docs/v11/split_v11_tablebench.json"
B, SEED = 2000, 2026


def num(c):
    try: return float(str(c).replace(",", "").replace("$", "").replace("%", "").strip())
    except ValueError: return None


def boot(n, fn):
    rng = random.Random(SEED); v = []
    for _ in range(B):
        ix = [rng.randrange(n) for _ in range(n)]; x = fn(ix)
        if x is not None: v.append(x)
    if not v: return None
    v.sort(); return [round(v[int(.025 * len(v))], 4), round(v[int(.975 * len(v)) - 1], 4)]


def mean(ix, a): return sum(a[i] for i in ix) / len(ix)


def main(pattern):
    ids = json.load(open(SPLIT))["ids"]
    docs = {d["questions"][0]["uid"]: d for d in json.load(open(DATA))}
    rows = {"agent_v9": {}, "rag": {}}
    for f in sorted(glob.glob(pattern)):
        for l in open(f):
            r = json.loads(l)
            if r["system"] in rows: rows[r["system"]][r["id"]] = r
    missing = {k: [i for i in ids if i not in v] for k, v in rows.items()}
    n = len(ids); out = {"n_items": n, "missing_rows": {k: len(v) for k, v in missing.items()}}
    gold = {i: (rows["rag"].get(i) or rows["agent_v9"].get(i) or {}).get("gold") for i in ids}

    def sc(r):
        if not r or r.get("error") or not isinstance(r.get("output"), dict) or r["output"].get("answer") in (None, ""):
            return 0.0, 0.0, True
        e, _, s = score(r, {"answer": r["output"]["answer"], "scale": r["output"].get("scale")}); return e, s, False
    A = {k: [sc(rows[k].get(i)) for i in ids] for k in rows}
    triv = []
    for i in ids:
        cells = [num(c) for row in docs[i]["table"]["table"][1:] for c in row]; cells = [c for c in cells if c is not None]
        a = statistics.median(cells) if cells else 0.0
        triv.append(score({"gold": gold[i]}, {"answer": round(a, 4), "scale": ""}) if gold[i] else (0, 0, 0))
    sem = {"V7": [x[1] for x in A["agent_v9"]], "RAG": [x[1] for x in A["rag"]], "trivial": [t[2] for t in triv]}
    em = {"V7": [x[0] for x in A["agent_v9"]], "RAG": [x[0] for x in A["rag"]], "trivial": [t[0] for t in triv]}
    out["errors"] = {"V7": sum(x[2] for x in A["agent_v9"]), "RAG": sum(x[2] for x in A["rag"])}
    out["accuracy"] = {k: {"semantic": round(sum(sem[k]) / n, 4), "semantic_ci": boot(n, lambda ix, a=sem[k]: mean(ix, a)),
                           "em": round(sum(em[k]) / n, 4)} for k in sem}
    out["paired_semantic_diff"] = {f"{a} - {b}": {"diff": round((sum(sem[a]) - sum(sem[b])) / n, 4),
                                                  "ci": boot(n, lambda ix, a=a, b=b: mean(ix, sem[a]) - mean(ix, sem[b]))}
                                   for a, b in (("V7", "RAG"), ("V7", "trivial"), ("RAG", "trivial"))}
    # V9_full confidence layer on top of V7 answers
    dec, p, cdet, gate = [], [], [], []
    for i in ids:
        r = rows["agent_v9"].get(i); o = (r or {}).get("output") if isinstance((r or {}).get("output"), dict) else {}
        d = row_decision(o) if o and not (r or {}).get("error") else {"decision": "abstain", "p_correct": None}
        dec.append(d["decision"] == "answer"); p.append(d["p_correct"] if d["p_correct"] is not None else 0.0)
        cdet.append(float(o.get("confidence_det") or 0.0)); gate.append(1.0 if o.get("gate_passed") else 0.0)
    y = [int(s) for s in sem["V7"]]
    ans = [j for j in range(n) if dec[j]]

    def sel(ix):
        a = [j for j in ix if dec[j]]; return sum(y[j] for j in a) / len(a) if a else None
    net = {"V7+V9": [(1 if y[j] else -1) if dec[j] else 0 for j in range(n)],
           "V7": [1 if y[j] else -1 for j in range(n)], "RAG": [1 if s else -1 for s in sem["RAG"]]}
    out["v9"] = {"coverage": round(len(ans) / n, 4), "abstention_rate": round(1 - len(ans) / n, 4),
                 "selective_semantic_acc": round(sel(range(n)) or 0, 4), "selective_acc_ci": boot(n, sel),
                 "realized_risk_wrong_answered_over_n": round(sum(1 - y[j] for j in ans) / n, 4), "crc_alpha_target": 0.10,
                 "selective_minus_V7_acc": {"diff": round((sel(range(n)) or 0) - sum(y) / n, 4),
                                             "ci": boot(n, lambda ix: (sel(ix) or 0) - mean(ix, y))},
                 "auroc": {k: {"value": round(AU(y, s), 4), "ci": boot(n, lambda ix, s=s: AU([y[i] for i in ix], [s[i] for i in ix]))}
                           for k, s in (("V9_full", p), ("V7_confidence_det", cdet), ("traceability_gate", gate))},
                 "auroc_diff_V9_minus_V7conf": boot(n, lambda ix: AU([y[i] for i in ix], [p[i] for i in ix]) - AU([y[i] for i in ix], [cdet[i] for i in ix]))}
    out["net_score_correct+1_wrong-1_abstain0"] = {k: round(sum(v) / n, 4) for k, v in net.items()}
    out["net_paired"] = {f"V7+V9 - {b}": {"diff": round((sum(net["V7+V9"]) - sum(net[b])) / n, 4),
                                          "ci": boot(n, lambda ix, b=b: mean(ix, net["V7+V9"]) - mean(ix, net[b]))} for b in ("RAG", "V7")}
    sub = {}
    for j, i in enumerate(ids):
        s = docs[i]["source"]["qsubtype"]; sub.setdefault(s, []).append(j)
    out["by_subtype"] = {s: {"n": len(J), "V7": round(sum(sem["V7"][j] for j in J) / len(J), 3), "RAG": round(sum(sem["RAG"][j] for j in J) / len(J), 3),
                             "V9_coverage": round(sum(dec[j] for j in J) / len(J), 3)} for s, J in sorted(sub.items())}
    pd = out["paired_semantic_diff"]["V7 - RAG"]["ci"]; v9 = out["v9"]
    acc = {"A1_V7_beats_RAG": pd[0] > 0,
           "A2_V9_discriminates_and_helps": v9["auroc"]["V9_full"]["ci"][0] > 0.5 and bool(v9["selective_minus_V7_acc"]["ci"]) and v9["selective_minus_V7_acc"]["ci"][0] > 0,
           "A3_risk_within_alpha": v9["realized_risk_wrong_answered_over_n"] <= 0.10,
           "A4_net_beats_RAG": out["net_paired"]["V7+V9 - RAG"]["ci"][0] > 0}
    k = sum(acc[x] for x in ("A1_V7_beats_RAG", "A2_V9_discriminates_and_helps", "A4_net_beats_RAG"))
    out["acceptance"] = {**acc, "verdict": "WORKS" if k == 3 else ("PARTIAL" if k else "DOES_NOT_WORK"),
                         "rag_wins": pd[1] < 0}
    out["failures"] = [{"id": i, "q": docs[i]["questions"][0]["question"], "gold": docs[i]["source"]["stated_answer"],
                        "v7": ((rows["agent_v9"].get(i) or {}).get("output") or {}).get("answer") if isinstance((rows["agent_v9"].get(i) or {}).get("output"), dict) else None,
                        "v9_decision": "answer" if dec[j] else "abstain", "p": p[j], "rag_correct": bool(sem["RAG"][j])}
                       for j, i in enumerate(ids) if not y[j]]
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
