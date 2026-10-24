"""Secondary metric "semantic correctness" (declared, V7.1 development). It is ALWAYS reported next to the official
TAT-QA EM/F1 and never replaces them. It separates "did not know" from "knew but formatted it wrong".

Deterministic rules only (no LLM judge; an LLM judge was not needed for these categories and would add cost/noise):
- numbers: pred value x scale factor equals gold value x scale factor within 0.5% relative (or 0.01 absolute);
  ALSO counted correct if the bare number matches and only the scale label differs/missing ("-39.5" vs "-39.5 million"),
  or if a ratio/percent differs by x100. The SIGN is never relaxed.
- span: normalised gold contained in the normalised prediction (prediction no longer than 4x gold + 20 chars), or the
  normalised prediction equals the gold.
- multi-span: every gold item is contained in some predicted item (same containment rule).
"""
from __future__ import annotations
import re

FACT = {"": 1.0, "thousand": 1e3, "million": 1e6, "billion": 1e9, "percent": 1.0}


def norm(s) -> str:
    s = str(s).lower().replace("\u2019", "'").replace("\u2212", "-")
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    s = re.sub(r"[$€£%]", "", s)
    s = re.sub(r"\b(the|a|an)\b", " ", s)
    s = re.sub(r"[^\w\s.\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .")


def num(s) -> float | None:
    t = norm(s)
    neg = str(s).strip().startswith("(") and str(s).strip().endswith(")")
    t = re.sub(r"\b(thousand|million|billion|percent)s?\b", "", t).strip()
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.01, 0.005 * abs(b))


def _items(x) -> list[str]:
    if isinstance(x, (list, tuple)):
        return [str(i) for i in x if str(i).strip()]
    s = str(x if x is not None else "")
    return [s] if s.strip() else []


def _contains(pred: str, gold: str) -> bool:
    p, g = norm(pred), norm(gold)
    if not p or not g:
        return False
    return p == g or (g in p and len(p) <= 4 * len(g) + 20)


def semantic_correct(pred, pred_scale, gold, gold_scale, answer_type: str) -> tuple[bool, str]:
    P, G = _items(pred), _items(gold)
    if not P:
        return False, "empty prediction"
    if answer_type in ("arithmetic", "count") or (len(G) == 1 and num(G[0]) is not None and len(P) == 1 and num(P[0]) is not None):
        if len(P) != 1:
            return False, "list for a single number"
        pv, gv = num(P[0]), num(G[0])
        if pv is None or gv is None:
            return False, "non-numeric"
        if _close(pv * FACT.get(pred_scale or "", 1), gv * FACT.get(gold_scale or "", 1)):
            return True, "numeric match with scale"
        if _close(pv, gv):
            return True, "numeric match, scale label differs"
        if _close(pv * 100, gv) or _close(pv, gv * 100):
            return True, "numeric match x100 (ratio vs percent)"
        return False, "numeric mismatch"
    if answer_type == "multi-span" or len(G) > 1:
        ok = all(any(_contains(p, g) for p in P) for g in G)
        return ok, "all gold items contained" if ok else "missing gold item"
    ok = any(_contains(p, G[0]) for p in P)
    return ok, "gold span contained" if ok else "span mismatch"
