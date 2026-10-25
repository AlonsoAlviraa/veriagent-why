# V9.1 generalization study — pre-registration

Written and committed **before** any full run on the new sets (only declared 15-16 item pilots on disjoint documents were run,
for pipeline checks). Sets: `docs/V9_GEN_SETS.md`. Analysis code: `bench/v9_gen_analysis.py` (committed with this file).
Question: which confidence / abstention strategy generalizes beyond TAT-QA, and which is overfit to the V9 design slice?

## 1. Data and runs
* Sets: `gen_secq`, `gen_jfinqa`, `gen_finqa` (400 items each; cal / test split by document). Each set is run **once** on all
  cal + test ids with `agent_v9` (V7 answer + all V9 signals) and with the plain `rag` baseline. Only items that fail with an
  infrastructure error are retried; no item is re-run because of its answer.
* Not used for any selection: test500, oodsec, the V9 design slice, earlier slices. test500 / oodsec numbers are cited only as
  already-reported references (the stability table recomputes oodsec AUROC for the new ablation arms from the existing
  `final_oodsec` rows; no new model call).
* Budget: Nebius cumulative cap $20 (ledger at start ≈ $8.04), `NEBIUS_STRICT=1`. If the ledger reaches $15 the remaining runs
  stop and the partial result is reported as such.

## 2. Correctness label
Primary: `semantic_correct` (bench.semantic: 0.5% relative tolerance, ×100 percent rule, scale-label-differs rule), because the
official TAT-QA EM is unreliable on FinQA / jfinqa (gold scale often missing, different rounding). Sensitivity: official TAT-QA
EM (AUROC also reported with this label). Models fitted on the design slice keep the design labels used in V9 (official EM).

## 3. Arms (all frozen; no re-tuning on new sets)
Answer systems: **plain RAG**, **V7** (agent answer). Metrics: EM, F1, semantic accuracy.

Confidence / abstention signals:
| Arm | Kind |
|---|---|
| `lex_frozen` | lexical signal, frozen threshold 0.809 |
| `raw_answer_token_prob` (**new arm**) | raw answer-token probability (`ans_msp`), no fitting |
| `raw_ptrue` | raw P(True), no fitting |
| `lex_platt` | logistic(lex) fitted on 600 design rows |
| `V8_refit` | logistic(V8 features + lex) |
| `V9_cheap` | logistic(lex + I1 logprobs + I2 P(True)/verbal) |
| `V9_full` | logistic(lex + I1 + I2 + I3 sampling + V8) |
| `abl_logprobs_only` | logistic(I1) |
| `abl_ptrue_only` | logistic(P(True)) |
| `abl_semantic_entropy_only` | logistic(semantic entropy) |
All logistic models: `bench.v8_report.logistic_fit`, fitted once on all 600 design rows. Design reference AUROC = 5-fold
GroupKFold-by-table out-of-fold AUROC on the design slice (raw arms: in-sample, nothing is fitted).

## 4. Metrics (on each set's test ids)
AUROC (item and table-cluster bootstrap 95% CI, 2000 resamples, seed 2026), ECE, Brier, AURC; selective accuracy at 50% and 80%
coverage; coverage at selective risk ≤ 10%; conformal risk control (alpha = 0.10, loss = answered AND wrong) with (a) the
threshold fitted on the design slice and (b) the threshold re-fitted on the set's own calibration split; paired AUROC differences
vs `lex_frozen` and vs `V9_cheap` (item and table bootstrap); cost per item. Cross-set stability: AUROC per arm for design → oodsec →
each new set, and Kendall tau of the arm ranking vs design.

## 5. Decision rule (per arm, over the three new sets)
* **GENERALIZES**: item-bootstrap AUROC lower 95% bound > 0.5 on every new set, AND mean AUROC drop vs design ≤ 0.05, AND the
  design-fitted CRC threshold keeps realized risk ≤ alpha + 0.02 on every new set.
* **OVERFIT / DOES NOT TRANSFER**: mean drop ≥ 0.10, OR the AUROC CI includes 0.5 on ≥ 2 new sets.
* Otherwise **PARTIAL**.
* Recommended signal = the GENERALIZES arm with the highest mean new-set AUROC; cost per item breaks near-ties (< 0.01). If no arm
  GENERALIZES, the recommendation is to claim no transferable abstention gain and report the best PARTIAL arm descriptively.
* Answer systems: V7 vs plain RAG reported with paired item bootstrap; no decision depends on it.
* Every result, including negative ones, is reported. Set-level failures (e.g. V7 accuracy outside 30-70%) are reported, not fixed.
