"""Read-only classifier of agent_mk failures from audit.json traces. Usage: python classify_errors.py <trace_dir> <out.csv>"""
import json, re, sys, csv, glob, os
from collections import Counter

def nums(s):
    out = []
    for m in re.findall(r"-?\(?\$?\d[\d,]*\.?\d*\)?", s or ""):
        neg = m.startswith("-") or m.startswith("(")
        v = re.sub(r"[^\d.]", "", m)
        try: out.append(-float(v) if neg else float(v))
        except ValueError: pass
    return out

def fnum(s):
    n = nums(str(s)); return n[0] if len(n) == 1 else None

def close(a, b, tol=0.006):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))

def classify(a):
    g = a["case"]["eval_only"]["gold"]; ga = g["answer"]; gold = [str(x) for x in (ga if isinstance(ga, list) else [ga])]
    fa = a["final_answer"]; ans = str(fa.get("answer", "")); sc = fa.get("scale", "") or ""
    s = a["scores"]; conf = a["confidence"]; steps = a["steps"]
    claims = a.get("claims", []); ev = a.get("evidence", [])
    gate = claims[-1]["gate_verdict"] if claims else "none"
    evtext = " ".join(e.get("text", "") for e in ev)
    ctx = next((st.get("prompt", "") for st in steps if st.get("prompt")), "")
    plan = " ".join(st.get("reply_head", "") or "" for st in steps if st.get("type") == "plan")
    route = next((st["decision"]["action"] for st in steps if st.get("type") == "route_decision" and st.get("decision")), "")
    tags = []
    pv, gv = fnum(ans), (fnum(gold[0]) if len(gold) == 1 else None)
    atype = g.get("answer_type", "")
    norm = lambda x: re.sub(r"[^a-z0-9.\- ]", "", x.lower().replace("\u201c", "").replace("\u201d", "")).strip()
    yr = lambda x: re.fullmatch(r"(fy)?\s?\d{2,4}", x.strip().lower()) is not None
    if not ans.strip() or ans.strip() in ("[]", "''"): tags.append("empty_answer")
    elif atype in ("arithmetic", "count"):
        if ans.strip().startswith("["): tags.append("format_list_for_scalar")
        elif pv is not None and gv is not None:
            if close(pv, gv) and sc != g.get("scale", ""): tags.append("scale_units")
            elif close(-pv, gv) and gv != 0: tags.append("wrong_sign")
            elif pv != 0 and any(close(pv, gv * k) for k in (100, 0.01, 1000, 0.001, 1e6, 1e-6)): tags.append("scale_units")
            elif close(pv, gv, 0.02): tags.append("rounding")
            elif any(close(pv, x) for x in nums(ctx)): tags.append("copied_context_number_not_computed")
            else: tags.append("wrong_operands_or_arithmetic")
        else: tags.append("unparseable_numeric")
    else:
        P, G = norm(ans), [norm(x) for x in gold]
        if s.get("f1", 0) >= 0.999: tags.append("format_normalization")
        elif atype == "multi-span" and 0 < s.get("f1", 0): tags.append("multi_span_partial")
        elif all(yr(x) for x in gold + [ans]) and len(gold) == 1: tags.append("wrong_year_comparison")
        elif any(x and P and x in P for x in G): tags.append("span_too_long")
        elif any(x and P and P in x for x in G): tags.append("span_truncated")
        elif s.get("f1", 0) > 0: tags.append("partial_span")
        elif ans in ctx or P in norm(ctx): tags.append("wrong_row_column_or_span")
        else: tags.append("off_target_answer")
    if not ev: tags.append("empty_evidence")
    if not ev and gate == "PASS": tags.append("empty_evidence_passed_gate")
    if gate == "PASS": tags.append("gate_passed_wrong")
    if plan and any(re.search(r"\"input\":\s*\"" + re.escape(gd), plan) for gd in gold if gd): tags.append("plan_had_gold_writer_changed")
    if (conf.get("model_self_reported") or 0) >= 0.95: tags.append("raw_conf_ge_0.95_wrong")
    return dict(id=a["case"]["item_id"], answer_type=atype, route=route, question=a["case"]["question"][:160],
                pred=ans, pred_scale=sc, gold="|".join(gold), gold_scale=g.get("scale", ""), f1=s.get("f1"),
                gate=gate, conf_det=conf.get("deterministic"), conf_raw=conf.get("model_self_reported"),
                n_evidence=len(ev), cause_index=s.get("failure", {}).get("cause"), primary=tags[0], tags=";".join(tags))

def main(td, out):
    rows, total = [], 0
    for p in sorted(glob.glob(os.path.join(td, "**", "*.audit.json"), recursive=True)):
        a = json.load(open(p)); total += 1
        if a["scores"].get("em", 0) >= 1: continue
        rows.append(classify(a))
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print("traces", total, "wrong", len(rows))
    print("primary", Counter(r["primary"] for r in rows).most_common())
    print("all tags", Counter(t for r in rows for t in r["tags"].split(";")).most_common())

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
