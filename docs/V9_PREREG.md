# V9 pre-registration (written and committed before any V9 design-slice run)

**Frozen config hash:** `ee774546ef9ccf14` = sha256 over the sha256 of `bench/{v9,v9_report,llmio,nebius,tatqa,v8}.py`, `docs/v9/{design,holdout}.json`,
the constants `V9_K=3 V9_SC_T=0.7 V8_K=5 V8_SC_T=0.7 ALPHA=0.10 SEED=9009` and the (secret-free) run env below.

## Data
TAT-QA **dev is fully burned** (positions 0-1667 all used by the abstention fit, V7.1 and V8). V9 therefore uses **TAT-QA train**:
tables shuffled with seed 9009; every question id appearing in any committed repo file (calibration/feature samples, splits) or in
earlier box-only battery runs (`docs/v9/excluded_extra.json`) is excluded; design and hold-out are **table-disjoint**.

| slice | n | sha256 (file) |
|---|---|---|
| design | 600 | 86188e4997b0b62018480815dd80785c5e17ee7aa54c6afb868ac819ae6f8d7a |
| hold-out | 400 | 16ae9eebbe5b1caaaef480252a893293dd5ab99daa5b71e2105425841645e5f6 |

Caveat (disclosed): the model may have seen TAT-QA train during pre-training more than dev; absolute EM on train is not comparable
to V7/V8 dev numbers. Comparisons are **within-slice**: V7, V8 (pointer features re-run on the same items) and V9 on identical items.
test500 is not used.

## Run env
`LLM_PROVIDER=nebius NEBIUS_MODEL=nvidia/Nemotron-3_5-Lightning (all tiers) NEBIUS_STRICT=1 NEBIUS_BUDGET_USD=20 LLM_CACHE=0
BENCH_SINGLE_MODEL=1 CR_USE_CALIB=0 AUDIT_TRACE=1 MODEL_TIMEOUT_S=120 V9=1 TATQA_SPLIT=train`, system `agent_v9`, all V9 flags on.
Spend cap for V9: +$6 over the ledger at start (7.2535); hard ledger cap $20.

## Arms
* Answer system = V7 (`agent_markov`) unchanged for every confidence arm.
* **I3b** (only answer-changing arm): majority over {V7 answer} ∪ 3 samples of V7's exact final evidence prompt at T=0.7; V7 wins ties.
* Confidence candidates (target: V7 official EM on the item):
  lex_frozen (thr 0.809), lex_platt, I1_msp_raw, I2_ptrue_raw, I2_verbal_raw, I3_v7share_raw (no fit),
  **V8_refit** (V8 pointer features + lex, logistic), **V9_cheap** (lex + I1 + I2, logistic; +1 call), **V9_full** (lex + I1 + I2 + I3 + V8 feats).
* Fitted scores are out-of-fold, **GroupKFold by table** (k=5, seed 9009).
* I4: conformal risk control on each fitted score, loss = answered∧wrong, α=0.10, calibrated out-of-fold.

## Acceptance (Code Reviewer rule)
* Answer change (I3b): ΔEM > 0 **and** broken ≤ fixed/3 vs V7 (McNemar + bootstrap CI reported).
* Confidence: AUROC and/or ECE improve with bootstrap 95% CI (2000 item resamples, seed 2026) excluding 0.
  **Primary:** H1 V9_cheap vs lex_platt; H2 V9_full vs V8_refit. Everything else is secondary/exploratory (multiple comparisons; not claims).
* Metrics: EM, F1 (official TAT-QA scorer), semantic EM, AUROC, ECE, Brier, AURC, selective EM and coverage at frozen-lex coverage,
  McNemar, bootstrap CI, cost (calls, seconds, tokens, USD per item).

## Hold-out
One single run of the frozen config on `docs/v9/holdout.json`, **only after Alonso's explicit OK**; no tuning afterwards.
Design-slice results may only choose *which* pre-declared arm goes to hold-out (recorded in V9_ROUND_1.md before the hold-out).
