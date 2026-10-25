"""V10 hard sets (docs/V10_HARD_SETS.md). Built and fingerprinted BEFORE any model run on them. No model calls here.
Sets (TAT-QA JSON format, loaded with TATQA_SPLIT=<name>):
  hard_mhiertt  MultiHiertt dev (Zhao et al. ACL 2022, MIT). Multi-table + text financial reports. Kept: arithmetic questions whose
                FinQA-DSL program re-executes to the stated answer AND are "hard" (>=2 program steps, or evidence in >=2 tables,
                ). Grouped by report (sha of first table) for the cal/test split. All tables are flattened into one grid with "[Table k]" separator rows.
  hard_docfinqa DocFinQA test (Reddy et al. ACL 2024, kensho/DocFinQA, MIT). Full 10-K filings (~550k chars). Context is a FROZEN
                retrieval: filing split into ~2000-char chunks, BM25 (app.bm25) top-8 vs the question, computed here once and
                stored. Gold = safe re-evaluation of the dataset's Python program, kept only when it agrees with the stated answer.
                Per item we record whether every program literal appears in the retrieved text (operands_in_context): when false,
                the correct behaviour is to abstain.
Same protocol as V9.1: <=400 questions, split by document into calibration (25%) and test (75%), seed 20261025, plus a disjoint
15-item pilot pool. Usage: python -m bench.v10_hard_build <work dir with mh_dev.json, docfinqa_test.parquet> [mhiertt docfinqa]"""
from __future__ import annotations
import ast, hashlib, json, operator, random, re, sys
from html.parser import HTMLParser
from pathlib import Path
from bench import v9_gen_build as G
from app.bm25 import bm25

G.OUT = G.ROOT / "docs/v10/hard"
SEED, N_MAX, N_PILOT = G.SEED, G.N_MAX, G.N_PILOT


class _T(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows, self.cell, self.span = [], None, 1
    def handle_starttag(self, t, a):
        if t == "tr": self.rows.append([])
        elif t in ("td", "th"): self.cell, self.span = "", int(dict(a).get("colspan") or 1)
    def handle_endtag(self, t):
        if t in ("td", "th") and self.cell is not None:
            self.rows[-1] += [self.cell.strip()] * self.span; self.cell = None
    def handle_data(self, d):
        if self.cell is not None: self.cell += d


def html_rows(h):
    p = _T(); p.feed(h); return [r for r in p.rows if any(c for c in r)]


def _gold(v, ans):
    a = ans.strip().replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"-?\d*\.?\d+%?", a) or isinstance(v, str): return None
    st = float(a.rstrip("%")); pct = a.endswith("%")
    if pct and G._close(v * 100, st, 0.01): return round(v * 100, 4), "percent"
    if G._close(v, st, 0.01): return round(v, 4), ("percent" if pct else "")
    return None


def _rep(x): return hashlib.sha256(x["tables"][0].encode()).hexdigest()[:16]


def build_mhiertt(work: Path):
    data = json.load(open(work / "mh_dev.json"))
    keep, drop = [], {"span_or_nonarith": 0, "program_error": 0, "disagree": 0, "not_hard": 0}
    for x in data:
        qa = x["qa"]
        if qa["question_type"] != "arithmetic" or not qa["program"]: drop["span_or_nonarith"] += 1; continue
        try: v = G.execute(qa["program"])
        except Exception: drop["program_error"] += 1; continue
        g = _gold(v, str(qa["answer"]))
        if g is None: drop["disagree"] += 1; continue
        steps = len(re.findall(r"\w+\(", qa["program"])); ntab = len({e.split("-")[0] for e in qa["table_evidence"]})
        hard = steps >= 2 or ntab >= 2
        if not hard: drop["not_hard"] += 1; continue
        keep.append((x, g, steps, ntab))
    rng = random.Random(SEED); rng.shuffle(keep)
    def doc(x, g, steps, ntab):
        uid = "hardmh-" + hashlib.sha256(x["uid"].encode()).hexdigest()[:16]
        grid = []
        for k, h in enumerate(x["tables"]): grid += [[f"[Table {k}]"]] + html_rows(h)
        paras = [{"uid": f"{uid}-p{i}", "order": i + 1, "text": t} for i, t in enumerate(x["paragraphs"]) if t.strip()]
        return {"table": {"uid": "hardmh-t-" + _rep(x), "table": grid}, "paragraphs": paras,
                "questions": [{"uid": uid, "order": 1, "question": x["qa"]["question"], "answer": g[0], "derivation": x["qa"]["program"],
                               "answer_type": "arithmetic", "answer_from": "table-text" if x["qa"]["text_evidence"] else "table",
                               "rel_paragraphs": [], "req_comparison": False, "scale": g[1]}],
                "source": {"multihiertt_uid": x["uid"], "stated_answer": str(x["qa"]["answer"]), "program_steps": steps, "tables_in_evidence": ntab}}
    main, pilot, pf = [], [], set()
    for x, g, s, n in keep:
        f = _rep(x)
        if len(pilot) < N_PILOT: pilot.append(doc(x, g, s, n)); pf.add(f); continue
        if f in pf: continue
        if len(main) < N_MAX: main.append(doc(x, g, s, n))
    for d in pilot: d["table"]["uid"] += "-pilot"
    return G._write("hard_mhiertt", main, pilot, {"source": "MultiHiertt dev (HF yilunzhao/MultiHiertt, MIT)", "filter": drop, "eligible": len(keep)})


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}
def safe_program(src):
    """Evaluate DocFinQA's straight-line arithmetic program without exec: only assignments of numbers/names/+-*/**."""
    env, lits = {}, []
    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): lits.append(n.value); return float(n.value)
        if isinstance(n, ast.Name): return env[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS: return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub): return -ev(n.operand)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("abs", "round", "min", "max") and not n.keywords:
            a = [ev(z) for z in n.args]; return {"abs": abs, "round": round, "min": min, "max": max}[n.func.id](*a)
        raise ValueError(ast.dump(n)[:80])
    for st in ast.parse("\n".join(l.strip() for l in src.splitlines() if l.strip())).body:
        if not (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name)): raise ValueError("stmt")
        env[st.targets[0].id] = ev(st.value)
    return env["answer"], lits


def _chunks(text, size=2000):
    out, cur = [], ""
    for p in re.split(r"\n\s*\n", text):
        while len(p) > size: out.append((cur + "\n" + p[:size]).strip()); cur, p = "", p[size:]
        if len(cur) + len(p) > size and cur: out.append(cur.strip()); cur = ""
        cur += "\n" + p
    if cur.strip(): out.append(cur.strip())
    return out


def _numin(v, text):
    t = text.replace(",", "")
    s = [f"{v:g}", f"{v:.1f}", f"{v:.2f}", str(int(v)) if float(v).is_integer() else "\0"]
    return any(re.search(r"(?<![\d.])" + re.escape(z) + r"(?![\d])", t) for z in s if z != "\0")


def build_docfinqa(work: Path, k=8):
    import pandas as pd
    df = pd.read_parquet(work / "docfinqa_test.parquet")
    idx = list(range(len(df))); random.Random(SEED).shuffle(idx)
    drop = {"no_program": 0, "program_error": 0, "disagree": 0}; main, pilot, pf, n_in = [], [], set(), 0
    for i in idx:
        if len(main) >= N_MAX: break
        r = df.iloc[i]
        if not r.Program.strip(): drop["no_program"] += 1; continue
        try: v, lits = safe_program(r.Program)
        except Exception: drop["program_error"] += 1; continue
        g = _gold(v, str(r.Answer))
        if g is None: drop["disagree"] += 1; continue
        fid = hashlib.sha256(r.Context[:5000].encode()).hexdigest()[:16]
        if fid in pf: continue
        ch = _chunks(r.Context); sc = bm25(ch, r.Question)
        top = sorted(sorted(range(len(ch)), key=lambda j: -sc[j])[:k])
        ret = "\n".join(ch[j] for j in top)
        ok = all(_numin(abs(z), ret) for z in lits if abs(z) not in (0, 1, 100, 1000, 1e6))
        uid = "harddf-" + hashlib.sha256(f"{i}|{r.Question}".encode()).hexdigest()[:16]
        d = {"table": {"uid": "harddf-t-" + fid, "table": [["(no separate table: the filing's tables appear inline in the retrieved excerpts)"]]},
             "paragraphs": [{"uid": f"{uid}-c{j}", "order": o + 1, "text": ch[j]} for o, j in enumerate(top)],
             "questions": [{"uid": uid, "order": 1, "question": r.Question, "answer": g[0], "derivation": r.Program, "answer_type": "arithmetic",
                            "answer_from": "text", "rel_paragraphs": [], "req_comparison": False, "scale": g[1]}],
             "source": {"docfinqa_test_row": i, "filing_fp": fid, "stated_answer": str(r.Answer), "n_chunks": len(ch), "retrieval": f"bm25 top-{k} of 2000-char chunks",
                        "operands_in_context": ok}}
        if len(pilot) < N_PILOT: pilot.append(d); pf.add(fid); continue
        main.append(d); n_in += ok
    for d in pilot: d["table"]["uid"] += "-pilot"
    return G._write("hard_docfinqa", main, pilot, {"source": "DocFinQA test (HF kensho/DocFinQA, MIT)", "filter": drop,
                                                   "operands_in_context_rate": round(n_in / max(1, len(main)), 3)})


if __name__ == "__main__":
    w = Path(sys.argv[1]); which = sys.argv[2:] or ["mhiertt", "docfinqa"]
    print(json.dumps({k: globals()[f"build_{k}"](w) for k in which}, indent=1, ensure_ascii=False))
