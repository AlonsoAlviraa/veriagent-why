"""Markovian control for the VeriAgent Why pipeline (v6.4): deterministic state -> action decisions.

HONEST SCOPE. The vendored Meterless Markovian engine (vendor/meterless/markovian) is a chunked-generation
orchestrator: it runs steps, carries a compressed [STATE_CHECKPOINT] between them and stops on [TASK_COMPLETE]
or maxChunks. It has no routing / policy / expected-gain API. So the *decision policy* here is our own code
(written for this hackathon), built on the same Markov property: every decision depends only on the current
compact state (never on the full history), and every transition is emitted as a Meterless-style
[STATE_CHECKPOINT] carryover string, so a log reader sees the same state protocol the engine uses.
No model call is made here; all decisions are pure functions of the state -> deterministic and unit-tested.

Decisions:
  route         TAT-QA: NUMERIC (calculator steps, react-style) vs EVIDENCE (single quoted-evidence answer);
                optional DEEP flag (final answer on a bigger model) from the NVIDIA classifier features.
  gate_retry    retry the Claim Gate only when expected gain >= GAIN_MIN (per-reason gain table), else stop.
  sql_repair    repair a failed SQL only for repairable error classes and never twice on the same error.
  requery       skip the Evidence Evaluator call when the evidence is already sufficient, or stop when the
                last round added nothing.
  rewrite       InsightBench gate: drop few unsupported insights instead of paying a rewrite call.
Both paths always keep the agent's evidence quotes, Claim Gate and citations.
"""
from __future__ import annotations
import json, re
from pathlib import Path

FEAT = Path(__file__).resolve().parent / "features"
GAIN_MIN = 0.25
RELEVANCE_MIN = 0.001  # TAT-QA TRAIN calibration (scripts/calib_relevance.py, n=150): 5th pct of gold-evidence p; was 0.05 (dev-tuned)
# Expected gain of one more gate round, by rejection reason (declared priors, fixed; not fitted on test items).
GATE_GAIN = {"empty_answer": 0.5, "answer_mismatch": 0.5, "number_not_in_context": 0.4, "no_expression": 0.3, "bad_expression": 0.4, "evidence_quote": 0.4}
# fix B1: evidence_quote was 0.1 (< GAIN_MIN), so a quote-format rejection STOPPED the gate instead of retrying;
# one re-quote round recovers most of them (baseline agent always retried), and quotes ARE the Track 02 citations.
REPAIRABLE = ("Binder Error", "Catalog Error", "Parser Error", "Conversion Error", "syntax error", "does not exist", "not found")
NUMERIC_Q = re.compile(r"\b(change|percentage|percent|average|ratio|difference|differ|total|sum|increase|decrease|growth|"
                       r"proportion|rate|how much (?:more|less|higher|lower)|what (?:is|was) the (?:mean|net))\b", re.I)
# NVIDIA classifier thresholds: top quarter (q75) of prompt_complexity_score, NO gold labels, NO results.
# Calibration data only: TAT-QA TRAIN (seeded 1000-question sample, bench/features/nvclf-tatqa-train.json) and the
# 30 InsightBench TUNE tasks (bench/splits/insightbench_split.json). Dev / the 70 eval tasks are never used.
DEEP_COMPLEXITY = {"tatqa": 0.1405, "insightbench": 0.2516}
DEEP_REASONING = 0.5
# Main table: Lightning for every config (fair). "controller + Super deep route" variant: DEEP_MODEL=nvidia/nemotron-3-super-120b-a12b
DEEP_MODEL = __import__("os").environ.get("DEEP_MODEL", "nvidia/Nemotron-3_5-Lightning")


def load_features(bench: str) -> dict:
    p = FEAT / f"nvclf-{bench}.json"
    return json.loads(p.read_text())["items"] if p.exists() else {}


class Controller:
    def __init__(self, use_nv: bool = False, nv: dict | None = None, bench: str = "tatqa"):
        self.use_nv, self.nv, self.thr = use_nv, (nv or {}), DEEP_COMPLEXITY[bench]
        self.log: list[dict] = []

    def _d(self, decision: str, state: dict, action: str, reason: str) -> str:
        ck = "[STATE_CHECKPOINT]\n" + "\n".join(f"{k.upper()}: {v}" for k, v in state.items()) + f"\nDECISION: {decision}={action}"
        import time as _t  # audit trace: wall-clock order so decisions can be interleaved with model calls
        self.log.append({"decision": decision, "state": state, "action": action, "reason": reason, "carryover": ck, "t": round(_t.time(), 3)})
        return action

    # ---------------- TAT-QA
    def route(self, question: str, item_id: str = "") -> dict:
        numeric = bool(NUMERIC_Q.search(question))
        st = {"numeric_cue": numeric}
        f = self.nv.get(item_id) if self.use_nv else None
        deep = False
        if f:
            st |= {"nv_task": f["task_type_1"], "nv_complexity": f["prompt_complexity_score"], "nv_reasoning": f["reasoning"]}
            deep = numeric and (f["prompt_complexity_score"] >= self.thr or f["reasoning"] >= DEEP_REASONING)
        path = "NUMERIC" if numeric else "EVIDENCE"
        why = ("computation cue in question" if numeric else "no computation cue: span/lookup answer, calculator steps skipped")
        if f:
            why += f"; NVIDIA classifier complexity={f['prompt_complexity_score']} reasoning={f['reasoning']} -> {'DEEP' if deep else 'FAST'}"
        self._d("route", st, path + ("+DEEP" if deep else ""), why)
        return {"path": path, "deep": deep, "model": DEEP_MODEL if deep else None}

    @staticmethod
    def reason_kind(r: str) -> str:
        if r.startswith("empty answer"):
            return "empty_answer"
        if r.startswith("evidence not found"):
            return "evidence_quote"
        if r.startswith("answer "):
            return "answer_mismatch"
        if r.startswith("expression number"):
            return "number_not_in_context"
        if r.startswith("expression does not"):
            return "bad_expression"
        return "no_expression"

    def gate_retry(self, reasons: list[str], round_: int, answer_traceable: bool, max_rounds: int = 2) -> bool:
        kinds = sorted({self.reason_kind(r) for r in reasons})
        gain = max((GATE_GAIN[k] for k in kinds), default=0.0)
        st = {"gate_round": round_, "reasons": kinds, "expected_gain": gain, "answer_traceable": answer_traceable}
        if not reasons:
            return self._d("gate", st, "ACCEPT", "gate passed") == "RETRY"
        if round_ + 1 >= max_rounds:
            return self._d("gate", st, "STOP", "gate round cap reached") == "RETRY"
        if gain < GAIN_MIN:
            return self._d("gate", st, "STOP", f"expected gain {gain} < {GAIN_MIN} (only quote-format issues); LLM call skipped") == "RETRY"
        return self._d("gate", st, "RETRY", f"expected gain {gain} >= {GAIN_MIN}") == "RETRY"

    def evidence_check(self, p_rel: float | None, round_: int, gate_ok: bool, max_rounds: int = 2) -> bool:
        """NVIDIA reranker relevance of (question, quoted evidence) as a gate input. RELEVANCE_MIN is calibrated on TAT-QA TRAIN
        only (scripts/calib_relevance.py: 5th percentile of p on gold evidence, n=150); dev is never used for tuning."""
        st = {"gate_round": round_, "gate_ok": gate_ok, "rerank_p": p_rel}
        if p_rel is None:
            return self._d("evidence_check", st, "NO_SIGNAL", "reranker unavailable; numeric gate only") == "RETRY"
        if not gate_ok or p_rel >= RELEVANCE_MIN:
            return self._d("evidence_check", st, "ACCEPT", f"p={p_rel} >= {RELEVANCE_MIN} or numeric gate already handled it") == "RETRY"
        if round_ + 1 >= max_rounds:
            return self._d("evidence_check", st, "FLAG", "low relevance but round cap; confidence lowered") == "RETRY"
        return self._d("evidence_check", st, "RETRY", f"quoted evidence weakly relevant (p={p_rel} < {RELEVANCE_MIN}); re-quote") == "RETRY"

    # ---------------- InsightBench
    def sql_repair(self, err: str, attempts: int, prev_err: str | None, max_attempts: int = 2, repeat_sql: bool = False) -> bool:
        cls = next((c for c in REPAIRABLE if c.lower() in err.lower()), "other")
        st = {"error_class": cls, "attempts": attempts, "same_as_previous": bool(prev_err and prev_err[:120] == err[:120]), "repeat_sql": repeat_sql}
        if repeat_sql:  # trace-fix 5: the repair returned a query already tried; never re-run it
            return self._d("sql_repair", st, "GIVE_UP", "repair returned an SQL identical to one already tried; not re-run") == "REPAIR"
        if attempts >= max_attempts:
            return self._d("sql_repair", st, "GIVE_UP", "repair cap reached") == "REPAIR"
        if cls == "other" and attempts >= 1:  # fix B7: unknown classes got 0 repairs (baseline: 1); now 1 try
            return self._d("sql_repair", st, "GIVE_UP", "unknown error class, one repair already tried") == "REPAIR"
        if st["same_as_previous"]:
            return self._d("sql_repair", st, "GIVE_UP", "repair reproduced the same error; low expected gain") == "REPAIR"
        return self._d("sql_repair", st, "REPAIR", f"{cls} is usually fixable from the schema" if cls != "other" else "unknown error class: one repair attempt") == "REPAIR"

    def requery(self, round_: int, n_ok: int, n_err: int, new_ok: int, max_rounds: int, n_empty: int = 0) -> bool:
        """trace-fix 2: n_ok counts only results with >=1 non-null row; empty results are gaps (REPORT.md pattern 5:
        "evidence sufficient (>=5 successful queries)" was logged with 0-row results)."""
        st = {"round": round_, "usable_results": n_ok, "empty_results": n_empty, "failed_results": n_err, "new_usable_this_round": new_ok, "max_rounds": max_rounds}
        if round_ + 1 >= max_rounds:
            return self._d("requery", st, "STOP", "round cap" + (f" ({n_empty} empty / {n_err} failed results remain as gaps)" if n_empty or n_err else "")) == "EVALUATE"
        if round_ > 0 and new_ok == 0:
            return self._d("requery", st, "STOP", "last round added no usable evidence; expected gain low") == "EVALUATE"
        if n_ok >= 5 and n_err == 0 and n_empty == 0:
            return self._d("requery", st, "STOP", "evidence sufficient (>=5 non-empty results, 0 errors, 0 empty); evaluator call skipped") == "EVALUATE"
        return self._d("requery", st, "EVALUATE", "gaps remain: " + ", ".join(x for x in (f"{n_err} failed" if n_err else "", f"{n_empty} empty" if n_empty else "", f"only {n_ok} usable" if n_ok < 5 else "") if x)) == "EVALUATE"

    def calc_step(self, step: int, expr: str, obs: str, seen_exprs: set, prev_obs: str | None) -> bool:
        """trace-fix 6: stop the calculator loop when the expression or the observation repeats (REPORT.md pattern 1:
        31/150 items repeated the same calc up to 3 times). Returns True to continue."""
        rep_e, rep_o = expr in seen_exprs, prev_obs is not None and obs == prev_obs
        st = {"step": step, "repeat_expression": rep_e, "repeat_observation": rep_o}
        if rep_e or rep_o:
            return self._d("calc", st, "STOP", "calculator " + ("expression" if rep_e else "observation") + " repeated: no progress; remaining calc calls skipped") == "CONTINUE"
        return self._d("calc", st, "CONTINUE", "new calculator result") == "CONTINUE"

    def insight_rounds(self, item_id: str) -> tuple[int, str | None]:
        f = self.nv.get(item_id) if self.use_nv else None
        if not f:
            self._d("depth", {"nv": False}, "ROUNDS=2", "default depth for Markovian control")
            return 2, None
        hard = f["prompt_complexity_score"] >= self.thr or f["reasoning"] >= DEEP_REASONING
        st = {"nv_task": f["task_type_1"], "nv_complexity": f["prompt_complexity_score"], "nv_reasoning": f["reasoning"]}
        self._d("depth", st, "ROUNDS=3+DEEP_WRITER" if hard else "ROUNDS=2", "NVIDIA classifier says " + ("hard" if hard else "easy"))
        return (3, DEEP_MODEL) if hard else (2, None)

    def rewrite(self, n_ins: int, n_bad: int, summary_bad: bool, round_: int, prev_bad: int | None, max_rounds: int) -> bool:
        frac = n_bad / n_ins if n_ins else 0.0
        st = {"gate_round": round_, "insights": n_ins, "failed": n_bad, "failed_share": round(frac, 3), "summary_unsupported": summary_bad}
        if not n_bad and not summary_bad:
            return self._d("rewrite", st, "ACCEPT", "gate passed") == "REWRITE"
        if round_ >= max_rounds:
            return self._d("rewrite", st, "DROP", "rewrite cap; unsupported insights dropped") == "REWRITE"
        if prev_bad is not None and n_bad >= prev_bad:
            return self._d("rewrite", st, "DROP", "previous rewrite did not reduce failures; expected gain low") == "REWRITE"
        if not summary_bad and n_ins - n_bad >= 3 and frac <= 0.25:
            return self._d("rewrite", st, "DROP", "few failures, >=3 supported insights remain; rewrite call skipped") == "REWRITE"
        return self._d("rewrite", st, "REWRITE", "many unsupported claims; rewrite expected to recover insights") == "REWRITE"
