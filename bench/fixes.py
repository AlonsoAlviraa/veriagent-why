"""Trace-audit fixes (docs/TRACE_FIXES.md; diagnosis: trace_audit/REPORT.md). Pure, deterministic helpers, no model calls.

1  span_extend / shorter_revision   full answer-span extraction for TAT-QA text answers; a revision that only trims
                                    the original span is rejected.
2  is_empty_result                  an SQL result with 0 data rows (or only NULLs) is a gap, not evidence.
3  check_comparatives               superlative / comparative claims are checked against the cited table values.
5  sql_key                          normalised SQL text so an identical repaired query is detected and not re-run.
6  CallCache (llmio), calc repeat   identical calls are served from cache within an item; the calc loop stops on repeats.
7  magnitude_rewrite                a revision that only rescales the original value (x10^k) is rejected.
Every helper only reads the question, the context and the system's own output. Gold is never read here.
"""
from __future__ import annotations
import json, re
from .common import nums

# ------------------------------------------------------------------ 1. spans
_SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\"'])")
SPAN_MODE = "off"  # TRAIN replay (n=180, scripts/fit_trace_fixes.py span): off 0.644 = end 0.644 > sentence 0.639 -> off; split_years +0.017 adopted


def _is_num(s: str) -> bool:
    return bool(re.fullmatch(r"\s*[-(]?[$€£]?\s*[\d,.]+\s*%?\)?\s*", str(s)))


def sentences(paras: list[str]) -> list[str]:
    out = []
    for p in paras:
        out += [s.strip() for s in _SENT.split(p) if s.strip()]
    return out


def span_extend(answer, paras: list[str], mode: str | None = None) -> tuple[object, str | None]:
    """Text span that stops before the end of its sentence/clause -> extend it to the end of that sentence
    (mode "end") or return the whole sentence ("sentence"). Numeric answers, lists, single words and answers
    not found verbatim are returned unchanged. Returns (answer, rule applied or None)."""
    mode = mode or SPAN_MODE
    if mode == "off" or not isinstance(answer, str) or _is_num(answer) or len(answer.split()) < 3:
        return answer, None
    a = answer.strip().rstrip(".")
    for s in sentences(paras):
        i = s.lower().find(a.lower())
        if i < 0:
            continue
        full = s.rstrip()
        if mode == "sentence":
            new = full
        else:
            new = full[i:]
        new = new.rstrip()
        if len(new.rstrip(".")) > len(a) + 1:
            return new, f"span_extend:{mode}"
        return answer, None
    return answer, None


_YEARS = re.compile(r"^\s*((?:19|20)\d\d)(?:\s*,\s*((?:19|20)\d\d))*\s*,?\s*(?:and|&)\s*((?:19|20)\d\d)\s*$")


def split_years(answer) -> tuple[object, str | None]:
    """'2019 and 2018' / '2017, 2018 and 2019' -> ['2019', '2018'] / [...]: a multi-span answer typed as one string."""
    if isinstance(answer, str) and _YEARS.match(answer):
        return re.findall(r"(?:19|20)\d\d", answer), "split_years"
    return answer, None


def _nk(s) -> str:
    if isinstance(s, list):
        return " | ".join(_nk(x) for x in s)
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def shorter_revision(base, rev, ctx: str) -> bool:
    """True when a revision only trims the original text span (rev is a strict sub-span of base) and the original
    span occurs verbatim in the context. Such revisions are rejected (REPORT.md pattern 3, ec290759)."""
    b, r = _nk(base), _nk(rev)
    if not b or not r or b == r or _is_num(str(base)) or _is_num(str(rev)):
        return False
    return r in b and b in _nk(ctx)


# ------------------------------------------------------------------ 7. magnitude
def magnitude_rewrite(base, rev) -> bool:
    """True when rev == base * 10^k (k in +-2, +-3, +-6, +-9): a scale rewrite, not a recomputation."""
    a, b = nums(str(base)), nums(str(rev))
    if len(a) != 1 or len(b) != 1 or not a[0] or not b[0] or abs(a[0] - b[0]) < 1e-9:
        return False
    for k in (2, 3, 6, 9):
        for f in (10 ** k, 10 ** -k):
            if abs(a[0] * f - b[0]) <= max(0.011, 0.005 * abs(b[0])):
                return True
    return False


def scale_in_source(base: dict, it: dict) -> bool:
    """True when the context states the base answer's scale explicitly (e.g. '(in millions)' / 'in thousands') -
    then a revision may not rewrite that scale (trace-fix 7; REPORT.md 0f5bcfe8, 3bc9ea91, 4a58213e)."""
    sc = str(base.get("scale") or "").lower()
    if sc not in ("thousand", "million", "billion"):
        return False
    doc = it.get("doc") or {}
    txt = json.dumps(doc.get("table", {}), default=str).lower() + " " + " ".join(p.get("text", "") for p in doc.get("paragraphs", [])).lower()
    return bool(re.search(rf"\b(in|\$|usd|eur)\s*(\w+\s+)?{sc}s?\b", txt)) or f"{sc}s)" in txt


def revision_guard(base: dict, rev: dict, it: dict, ctx: str) -> str | None:
    """Reason string when a critic/PoT revision must be rejected (fixes 1 + 7), else None."""
    if shorter_revision(base.get("answer"), rev.get("answer"), ctx):
        return "revision only trims the original span, which occurs verbatim in the context"
    if magnitude_rewrite(base.get("answer"), rev.get("answer")):
        return "revision is the original value times 10^k (scale rewrite, not a recomputation)"
    if (base.get("scale") or "") and (rev.get("scale") or "") != (base.get("scale") or "") and scale_in_source(base, it):
        return f"scale change {base.get('scale')!r}->{rev.get('scale')!r}: the source states the scale"
    return None


# ------------------------------------------------------------------ 2. empty results
def is_empty_result(res: str) -> bool:
    """bench.insightbench.run_sql output: 'cols\\nrow\\nrow'. 0 data rows, or every data cell None/NULL/NaN/''."""
    if res is None or str(res).startswith("ERROR"):
        return False
    lines = [l for l in str(res).split("\n")[1:] if l.strip()]
    if not lines:
        return True
    cells = [c.strip().lower() for l in lines for c in l.split(" | ")]
    return all(c in ("none", "null", "nan", "nat", "") for c in cells)


def usable(res: str) -> bool:
    return bool(res) and not str(res).startswith("ERROR") and not is_empty_result(res)


# ------------------------------------------------------------------ 3. comparatives
HI = r"highest|largest|longest|greatest|biggest|most|maximum|max|top|peak|slowest"
LO = r"lowest|smallest|shortest|least|fewest|minimum|min|fastest"
_SUP = re.compile(rf"\b(?:the\s+)?({HI}|{LO})\b", re.I)
_CMP = re.compile(r"\b(more|higher|greater|larger|longer|less|lower|smaller|shorter|fewer)\s+than\b", re.I)


def parse_table(res: str) -> tuple[list[str], list[list[str]]]:
    lines = [l for l in str(res or "").split("\n") if l.strip()]
    if len(lines) < 2 or str(res).startswith("ERROR"):
        return [], []
    return [c.strip() for c in lines[0].split(" | ")], [[c.strip() for c in l.split(" | ")] for l in lines[1:]]


def _f(c: str):
    try:
        return float(str(c).replace(",", ""))
    except ValueError:
        return None


def _rows_for(text: str, cols, rows):
    """Rows whose (non-numeric) label cell is mentioned in the claim text (longest label first)."""
    t = text.lower()
    hits = []
    for r in rows:
        for c in r:
            if _f(c) is None and len(c) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(c.lower()) + r"(?![a-z0-9])", t):
                hits.append((t.find(c.lower()), r, c))
                break
    return sorted(hits, key=lambda h: h[0])


def _col(text: str, cols, rows, row) -> int | None:
    """Numeric column to compare: the one whose value in `row` is quoted in the claim, else the last numeric column."""
    tn = nums(text)
    numc = [j for j in range(len(cols)) if sum(_f(r[j]) is not None for r in rows if j < len(r)) >= max(1, len(rows) - 1)]
    for j in numc:
        v = _f(row[j]) if j < len(row) else None
        if v is not None and any(abs(v - x) <= max(0.006, 0.006 * abs(v)) for x in tn):
            return j
    return numc[-1] if numc else None


def check_comparatives(text: str, sources: list[str]) -> list[dict]:
    """Deterministic argmax/argmin check of superlatives ('Hardware has the longest ...') and 'X more than Y'
    claims against each cited table. Returns contradictions [{kind, claimed, actual, column, source}]; [] when the
    claim is consistent or cannot be checked (no label/column match: never guesses)."""
    bad = []
    for si, src in enumerate(sources):
        cols, rows = parse_table(src)
        if len(rows) < 2:
            continue
        hits = _rows_for(text, cols, rows)
        if not hits:
            continue
        m = _SUP.search(text)
        if m and len(hits) == 1:
            row, label = hits[0][1], hits[0][2]
            j = _col(text, cols, rows, row)
            if j is not None:
                hi = re.fullmatch(HI, m.group(1).lower()) is not None
                vals = [(_f(r[j]), r) for r in rows if j < len(r) and _f(r[j]) is not None]
                best = max(vals, key=lambda x: x[0]) if hi else min(vals, key=lambda x: x[0])
                mine = _f(row[j])
                if mine is not None and (best[0] > mine if hi else best[0] < mine):
                    bad.append({"kind": "superlative", "word": m.group(1), "claimed": label, "column": cols[j],
                                "claimed_value": mine, "actual": " ".join(c for c in best[1] if _f(c) is None) or str(best[1]), "actual_value": best[0], "source": si})
        c = _CMP.search(text)
        if c and len(hits) >= 2:
            (_, ra, la), (_, rb, lb) = hits[0], hits[1]
            j = _col(text, cols, rows, ra)
            if j is not None and j < len(rb):
                va, vb = _f(ra[j]), _f(rb[j])
                up = c.group(1).lower() in ("more", "higher", "greater", "larger", "longer")
                if va is not None and vb is not None and (va <= vb if up else va >= vb):
                    bad.append({"kind": "comparative", "word": c.group(1), "claimed": f"{la} vs {lb}", "column": cols[j],
                                "claimed_value": va, "actual_value": vb, "source": si})
    return bad


# ------------------------------------------------------------------ 5. SQL
def sql_key(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", str(sql or ""))).strip().rstrip(";").strip().lower()


# ------------------------------------------------------------------ 4. isotonic calibration
def isotonic_fit(xs: list[float], ys: list[float]) -> list[list[float]]:
    """Pool-adjacent-violators. Returns a monotone step map [[x_hi, y], ...] (Laplace-smoothed per block)."""
    pts = sorted(zip(xs, ys))
    blocks = []  # [sum_y, n, x_hi]
    for x, y in pts:
        blocks.append([y, 1, x])
        while len(blocks) > 1 and (blocks[-2][2] == blocks[-1][2] or blocks[-2][0] / blocks[-2][1] >= blocks[-1][0] / blocks[-1][1]):
            s, n, xh = blocks.pop()
            blocks[-1][0] += s; blocks[-1][1] += n; blocks[-1][2] = xh
    out, top = [], 0.0
    for s, n, xh in blocks:  # smoothing can break monotonicity on tiny blocks: keep a running max
        top = max(top, (s + 0.5) / (n + 1))
        out.append([round(xh, 4), round(top, 3)])
    return out


def isotonic_apply(cmap: list[list[float]] | None, x: float | None, default: float = 0.2) -> float:
    if x is None or not cmap:
        return default
    for hi, y in cmap:
        if x <= hi:
            return y
    return cmap[-1][1]
