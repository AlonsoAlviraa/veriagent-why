# V10 hard-set study: pre-registration

This file was written and committed **before any model call** on `hard_mhiertt` or `hard_docfinqa` (see `docs/V10_HARD_SETS.md`). Pilots are not run yet. Pilot results will be appended in §7 before the full runs.

**Question.** Does the final system (V7 answers + V9_full confidence) still rank its own errors well, and keep answered-risk controlled, when base accuracy is low (expected 25–50%)?

## 1. Data and runs
- Each set is run **once** on all cal + test ids with `agent_v9` (V7 answer + all V9 signals) and with plain `rag`.
- Only items that fail with an infrastructure error are retried.
- Pilots: 15 disjoint items per set, used only to check the pipeline and the cost.
- Analysis code: `bench/v9_gen_analysis.py`, unchanged apart from accepting the two set names. Any such change is committed before the full runs.

## 2. Label
- Primary: `semantic_correct` (as in V9.1).
- Sensitivity: official TAT-QA EM.

## 3. Arms (all frozen from V9.1; nothing re-tuned on the V10 sets)
- Answer systems: **plain RAG** and **V7**.
- Confidence: **V9_full** (logistic regression on lex + I1 + I2 + I3 + V8, fitted on the 600 design rows), **lex_frozen** (threshold 0.809), **raw_answer_token_prob** (`ans_msp`).
- Reported descriptively: V9_cheap and raw_ptrue.

## 4. Metrics (test ids)
- Accuracy (EM, F1, semantic).
- AUROC with item and cluster bootstrap 95% CIs (2000 resamples, seed 2026).
- AURC, ECE, Brier.
- Selective accuracy at 30/50/80% coverage.
- **Coverage at selective risk ≤ 10% and ≤ 20%** (a fixed-risk operating point).
- Conformal risk control, alpha 0.10 and 0.20 (loss = answered and wrong), with (a) the design-fitted threshold and (b) the threshold re-fitted on each set's cal split.
- Paired AUROC difference, V9_full minus lex_frozen and V9_full minus raw_answer_token_prob.
- Cost per item.

**hard_docfinqa only:** AUROC and abstention rate split by `operands_in_context` (true/false). A good signal abstains more often when the operands are missing.

## 5. Decision rule
- **HOLDS** if V9_full meets both conditions on both sets:
  - the AUROC lower 95% bound is > 0.5
  - the re-fitted CRC threshold keeps realized test risk ≤ alpha + 0.03
- **FAILS** if the AUROC CI includes 0.5 on both sets.
- Otherwise **PARTIAL**.
- V9_full is "better than baselines" only if the paired item-bootstrap CI of the AUROC difference excludes 0.
- Every result is reported, including negatives. If V7 accuracy comes out above 60% the set is reported as "not hard", not replaced.

## 6. Budget and stop rule
- Nebius ledger at the start: **$9.63** of the $20 cap. `NEBIUS_STRICT=1`.
- Hard stop at **$15**: any partial result is reported as partial.
- Planned Nebius spend is about $2–2.5 per set, about $4.5–5 in total, giving an estimated ledger of about $14.3–14.6.
- If the pilot extrapolation exceeds $2.6 per set, run the test ids only (about 300) and skip the cal-split re-fit for that set.
- NVIDIA calls are free but rate-limited (40 requests/min).

## 7. Pilot results
Pilots ran on 25 Oct 2026 (15 disjoint items per set, `agent_v9` only, pilot items excluded from all results). Pipeline worked on both sets, 0 errors.

| Set | Pilot items | V7 official EM | V7 semantic | Pilot cost |
|---|---|---|---|---|
| hard_mhiertt | 15 | 0/15 | 10/15 | ≈ $0.074 (both pilots $0.147) |
| hard_docfinqa | 15 | 1/15 | 4/15 | ≈ $0.074 |

- Cost extrapolation: about $0.0049 per `agent_v9` item, so about $2.0 per set plus `rag`, under the $2.6 limit. Both sets run on all cal + test ids.
- hard_mhiertt official EM is 0/15 mostly because the gold answers are ratios (0.2365) while V7 answers percents (23.65); the semantic label accepts ×100, as pre-registered. On the semantic label the pilot is above the 60% "hard" line; per section 5 the set is not replaced.
- Ledger after pilots: $9.779.
- Analysis code: `bench/v10_analysis.py`, a thin wrapper over the unchanged `bench/v9_gen_analysis.py` that adds only the section 4 extras (30% coverage, risk ≤ 20%, CRC alpha 0.20, V9_full − raw token prob, DocFinQA operand strata) and the section 5 rule.
- Timing disclosure: the full runs were launched at about 12:24 Madrid, a few minutes before this section and `bench/v10_analysis.py` were committed. No full-run output was read before the commit.
