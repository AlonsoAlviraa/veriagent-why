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
RELEVANCE_MIN = 0.05
# Expected gain of one more gate round, by rejection reason (declared priors, fixed; not fitted on test items).
GATE_GAIN = {"answer_mismatch": 0.5, "number_not_in_context": 0.4, "no_expression": 0.3, "bad_expression": 0.4, "evidence_quote": 0.1}
REPAIRABLE = ("Binder Error", "Catalog Error", "Parser Error", "Conversion Error", "syntax error", "does not exist", "not found")
NUMERIC_Q = re.compile(r"\b(change|percentage|percent|average|ratio|difference|differ|total|sum|increase|decrease|growth|"
                       r"proportion|rate|how much (?:more|less|higher|lower)|what (?:is|was) the (?:mean|net))\b", re.I)
# NVIDIA classifier thresholds (declared). Set from the classifier's own score distribution on the sample
# (about the top quarter of prompt_complexity_score per benchmark), using NO gold labels and NO results.
DEEP_COMPLEXITY = {"tatqa": 0.145, "insightbench": 0.258}
DEEP_REASONING = 0.5
DEEP_MODEL = "nvidia/nemotron-3-super-120b-a12b"


def load_features(bench: str) -> dict:
    p = FEAT / f"nvclf-{bench}.json"
    return json.loads(p.read_text())["items"] if p.exists() else {}


class Controller:
    def __init__(self, use_nv: bool = False, nv: dict | None = None, bench: str = "tatqa"):
        self.use_nv, self.nv, self.thr = use_nv, (nv or {}), DEEP_COMPLEXITY[bench]
        self.log: list[dict] = []

    def _d(self, decision: str, state: dict, action: str, reason: str) -> str:
        ck = "[STATE_CHECKPOINT]\n" + "\n".join(f"{k.upper()}: {v}" for k, v in state.items()) + f"\nDECISION: {decision}={action}"
        self.log.append({"decision": decision, "state": state, "action": action, "reason": reason, "carryover": ck})
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
        """NVIDIA reranker relevance of (question, quoted evidence) as a gate input. RELEVANCE_MIN was set on
        held-out TAT-QA dev items 41-100 (not the 40 evaluated): EM 0.42 when p<0.05 vs 0.61 when p>=0.5."""
        st = {"gate_round": round_, "gate_ok": gate_ok, "rerank_p": p_rel}
        if p_rel is None:
            return self._d("evidence_check", st, "NO_SIGNAL", "reranker unavailable; numeric gate only") == "RETRY"
        if not gate_ok or p_rel >= RELEVANCE_MIN:
            return self._d("evidence_check", st, "ACCEPT", f"p={p_rel} >= {RELEVANCE_MIN} or numeric gate already handled it") == "RETRY"
        if round_ + 1 >= max_rounds:
            return self._d("evidence_check", st, "FLAG", "low relevance but round cap; confidence lowered") == "RETRY"
        return self._d("evidence_check", st, "RETRY", f"quoted evidence weakly relevant (p={p_rel} < {RELEVANCE_MIN}); re-quote") == "RETRY"

    # ---------------- InsightBench
    def sql_repair(self, err: str, attempts: int, prev_err: str | None, max_attempts: int = 2) -> bool:
        cls = next((c for c in REPAIRABLE if c.lower() in err.lower()), "other")
        st = {"error_class": cls, "attempts": attempts, "same_as_previous": bool(prev_err and prev_err[:120] == err[:120])}
        if attempts >= max_attempts:
            return self._d("sql_repair", st, "GIVE_UP", "repair cap reached") == "REPAIR"
        if cls == "other":
            return self._d("sql_repair", st, "GIVE_UP", "non-repairable error class; LLM call skipped") == "REPAIR"
        if st["same_as_previous"]:
            return self._d("sql_repair", st, "GIVE_UP", "repair reproduced the same error; low expected gain") == "REPAIR"
        return self._d("sql_repair", st, "REPAIR", f"{cls} is usually fixable from the schema") == "REPAIR"

    def requery(self, round_: int, n_ok: int, n_err: int, new_ok: int, max_rounds: int) -> bool:
        st = {"round": round_, "ok_results": n_ok, "failed_results": n_err, "new_ok_this_round": new_ok, "max_rounds": max_rounds}
        if round_ + 1 >= max_rounds:
            return self._d("requery", st, "STOP", "round cap") == "EVALUATE"
        if round_ > 0 and new_ok == 0:
            return self._d("requery", st, "STOP", "last round added no usable evidence; expected gain low") == "EVALUATE"
        if n_ok >= 5 and n_err == 0:
            return self._d("requery", st, "STOP", "evidence sufficient (>=5 successful queries, 0 errors); evaluator call skipped") == "EVALUATE"
        return self._d("requery", st, "EVALUATE", "gaps or failed queries remain") == "EVALUATE"

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
