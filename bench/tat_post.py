"""Deterministic TAT-QA answer post-step (scale + format). Uses ONLY the question, the context
(table + paragraphs) and the system's own prediction. It never reads the gold answer or gold scale.

Rules (documented in docs/BENCHMARKS.md):
1. Format: strip $, commas and a trailing %; numeric single answers rounded to 2 decimals.
2. Scale:
   a. percent if the question asks for a percentage / percent / proportion / "%" or a percentage change;
   b. "" for non-numeric answers, counts ("how many" + small integer) and years;
   c. otherwise the unit the context states for the figures used: a number from the answer/expression
      found in a table whose header (or a paragraph) says "in thousands / in millions / $'000 / billion",
      or a number directly followed by "million/thousand/billion" in a paragraph;
   d. "" if the context states no unit for those figures.
"""
from __future__ import annotations
import re
from .common import nums

_PCT_Q = re.compile(r"percent|%|proportion|percentage", re.I)
_UNIT = [("billion", re.compile(r"\bin\s+billions?\b|\$\s*billions?\b|\bbillions?\s+of\b|\(\s*billions?\s*\)", re.I)),
         ("million", re.compile(r"\bin\s+millions?\b|\$\s*millions?\b|\bmillions?\s+of\b|\(\s*millions?\s*\)|\$\s*m\b|\$'?m\b|'000,000", re.I)),
         ("thousand", re.compile(r"\bin\s+thousands?\b|\$\s*thousands?\b|\bthousands?\s+of\b|\(\s*thousands?\s*\)|\$\s*['‘’]?000s?\b|['‘’]000s?\b|\$k\b", re.I))]


def _unit_of(text: str) -> str:
    for name, rx in _UNIT:
        if rx.search(text or ""):
            return name
    return ""


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.005, 1e-6 * abs(b))


def fmt_number(s: str) -> str:
    t = str(s).strip().replace("$", "").replace(",", "").strip()
    t = t.rstrip("%").strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    try:
        v = float(t)
    except ValueError:
        return str(s).strip()
    v = -v if neg else v
    v = round(v, 2)
    out = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if out in ("-0", "") else out


def _is_number(s) -> bool:
    try:
        float(str(s).replace("$", "").replace(",", "").replace("%", "").strip().strip("()"))
        return True
    except ValueError:
        return False


def infer_scale(question: str, answer, expression: str, doc: dict) -> str:
    q = question or ""
    vals = answer if isinstance(answer, list) else [answer]
    if not vals or not all(_is_number(x) for x in vals):
        return ""
    single = vals[0]
    if single is None or not _is_number(single):
        return ""
    v = float(fmt_number(single))
    if _PCT_Q.search(q) or "%" in str(single):
        return "percent"
    if re.match(r"\s*how many\b", q, re.I) and v == int(v) and abs(v) <= 50 and not _unit_of(q):
        return ""
    if all(float(fmt_number(x)) == int(float(fmt_number(x))) and 1900 <= float(fmt_number(x)) <= 2100 for x in vals) and re.search(r"\byears?\b|\bwhen\b", q, re.I):
        return ""
    used = [abs(x) for x in nums(expression or "")] or [abs(float(fmt_number(x))) for x in vals]
    table = doc["table"]["table"]
    head = " ".join(" ".join(r) for r in table[:3])
    paras = [p["text"] for p in doc.get("paragraphs", [])]
    t_unit = _unit_of(head) or _unit_of(" ".join(" ".join(r) for r in table))
    if not t_unit:  # paragraph that introduces the table: "... (in thousands)"
        for p in paras:
            if re.search(r"in (thousands|millions|billions)", p, re.I) and re.search(r"table|following", p, re.I):
                t_unit = _unit_of(p)
                break
    cells = [abs(x) for r in table for c in r for x in nums(c)]
    if t_unit and any(_close(u, c) for u in used for c in cells):
        return t_unit
    for p in paras:
        for m in re.finditer(r"\$?\s?(\d[\d,]*(?:\.\d+)?)\s*(million|thousand|billion)\b", p, re.I):
            x = float(m.group(1).replace(",", ""))
            if any(_close(u, x) for u in used):
                return m.group(2).lower()
    return ""


def flatten(answer):
    """List-of-dicts / dict answers (seen from Lightning) -> list of strings (fixes the scorer's sorted() TypeError)."""
    if isinstance(answer, dict):
        answer = list(answer.values())
    if isinstance(answer, list):
        out = []
        for a in answer:
            if isinstance(a, dict):
                out += [str(x) for x in a.values()]
            elif isinstance(a, list):
                out += [str(x) for x in a]
            else:
                out.append(str(a))
        return out
    if isinstance(answer, (int, float)):
        return str(answer)
    return "" if answer is None else str(answer)


def postprocess(pred: dict, question: str, doc: dict) -> dict:
    a = flatten(pred.get("answer"))
    sc = infer_scale(question, a, str(pred.get("expression") or ""), doc)
    if isinstance(a, list):
        a = [fmt_number(x) if _is_number(x) else x.strip() for x in a]
        if len(a) == 1:
            a = a[0]
    elif _is_number(a):
        a = fmt_number(a)
    return {**pred, "answer": a, "scale": sc}
