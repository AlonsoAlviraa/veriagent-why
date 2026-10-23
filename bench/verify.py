"""Verify-retry loop (config *_vr). After the generator answers, the answer is serialised as
{answer, claims[], evidence[]} and scored 0-100:
    score = W_DET * deterministic + (1 - W_DET) * verifier
deterministic = share of passed checks (every number traceable to the cited evidence, citations exist and match);
verifier = an LLM judgement by a DIFFERENT model (VERIFIER_MODEL, Nemotron Super; the generator is Lightning).
The verifier sees ONLY the question and the serialised answer + its cited evidence. It never sees gold, the
scorer or the full context. If score < THRESHOLD the generator regenerates with the verifier's feedback; at most
MAX_ATTEMPTS attempts, stopping early when the score has not improved for PATIENCE consecutive attempts.
The best-scoring attempt is returned and its score / 100 is the confidence (calibration measured with ECE/Brier).
THRESHOLD and W_DET are calibrated ONLY on TAT-QA train and the 30 InsightBench tuning tasks (docs/BENCHMARKS.md).
"""
from __future__ import annotations
import json, os

VERIFIER_MODEL = os.environ.get("VERIFIER_MODEL", "nvidia/nemotron-3-super-120b-a12b")
W_DET = float(os.environ.get("VR_W_DET", "0.5"))
THRESHOLD = float(os.environ.get("VR_THRESHOLD", "50"))
MAX_ATTEMPTS, PATIENCE = 5, 2

PROMPT = ("You are an independent verifier. You see a QUESTION and a candidate ANSWER (JSON) with the evidence it cites. "
          "You do NOT see the source document. Judge only: does the cited evidence actually support every claim and number, "
          "does the answer address the question, is any arithmetic consistent with the evidence. Reply with JSON only: "
          "{\"score\": integer 0-100, \"feedback\": \"one or two concrete sentences the author can act on\"}.")


def llm_verify(m, question: str, packet: dict) -> tuple[float | None, str]:
    out = m.call_json([{"role": "system", "content": PROMPT},
                       {"role": "user", "content": "QUESTION: " + question + "\nANSWER: " + json.dumps(packet)[:6000]}],
                      "verifier", "s2", 300, model=VERIFIER_MODEL)
    try:
        s = float(out.get("score"))
        return max(0.0, min(100.0, s)), str(out.get("feedback") or "")[:500]
    except (TypeError, ValueError):
        return None, ""


def loop(m, question: str, generate, check) -> dict:
    """generate(feedback|None) -> result; check(result) -> (packet, det 0-100, det_notes list[str])."""
    attempts, best, fb, stale = [], None, None, 0
    for k in range(MAX_ATTEMPTS):
        res = generate(fb)
        packet, det, notes = check(res)
        v, vfb = llm_verify(m, question, packet)
        score = round(W_DET * det + (1 - W_DET) * (v if v is not None else det), 2)  # verifier None: det only, counted
        prev = attempts[-1]["score"] if attempts else None
        attempts.append({"attempt": k + 1, "score": score, "det": round(det, 2), "verifier": v, "verifier_none": v is None,
                         "det_notes": notes[:6], "packet": packet if len(json.dumps(packet)) < 3000 else None, "feedback": vfb, "delta": None if prev is None else round(score - prev, 2)})
        if best is None or score > best[0]:
            best, stale = (score, res, k), 0
        else:
            stale += 1
        if score >= THRESHOLD or stale >= PATIENCE:
            break
        fb = ("Independent verifier score " + str(score) + "/100. " + vfb + (" Deterministic checks failed: " + "; ".join(notes[:4]) if notes else "")
              + " Fix these problems and answer again in the same JSON format.")
    score, res, k = best
    return {**res, "confidence": round(score / 100, 3), "vr_score": score, "vr_attempts": attempts,
            "vr_best_attempt": k + 1, "vr_n_attempts": len(attempts)}
