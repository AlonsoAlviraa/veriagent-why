# Pre-registration: TAT-QA test500 final evaluation (skeleton)

Committed **before any run on this split**. The config freeze is pending (V7 approval). Fields marked FREEZE are filled in by a separate commit before the run, and nothing changes after that.

## Split
- File: `bench/splits/tatqa_test500_v1.json`. File sha256: `226699d0786209749deabef62a000ab63fe87a6e211252ad3225119e870f3bab`.
- `ids_sha256`: `02b8820dcc24918f3394cc610dfeb89b81ba1bbc23eaba08db7443a241991f74`. This is the sha256 of the sorted ids joined with `\n`.
- Source: official TAT-QA `test_gold` (1663 questions), sha256 `c4d08418359c1d76468dec420ee748a37f48c06b63cb8ec2766f19d5d314b597`.
- Draw: `random.Random(20261023).sample(sorted(pool), 500)`.
  - pool = 1563 ids, after excluding the 100 pilot ids.
  - **Pilot exclusion:** the 100 ids in `bench/splits/holdout_v1.json` were run on 2026-10-23 before this decision. They are listed in `bench/splits/pilot_holdout_v1_manifest.json`, excluded from the draw, and are not part of any reported result.
- No tuning, calibration fitting or error inspection on these 500 items, ever. Calibration maps are fit on TAT-QA train only.

## Frozen config (filled at V7 freeze, before the run)
- Frozen code sha: `<TBD_CODE_SHA>`
- Config hash (sha256 of the canonical JSON of model, endpoint, arms, env flags, max_calls, rpm and calib file hashes): `<TBD_CONFIG_SHA256>`
- Freeze commit: `<TBD_FREEZE_COMMIT>`, at `<TBD_TIMESTAMP>`

## Run
- One run per arm, at T=0, from a clean commit. Rows carry `code_rev` and `dirty=false`. Dirty runs abort.
- FREEZE: commit sha, model id + endpoint, max calls, rpm, env flags (`CR_USE_CALIB`, …).
- Errored items are retried up to 3 resume passes. Items that are still failing count as wrong and are reported.

## Arms
- `rag`: retrieval baseline.
- `react`: reference.
- `agent_mk`: #7 baseline config.
- `agent_mk` + trace fixes.
- `agent_cr` + trace fixes.
- FREEZE: the exact arm list and their code_revs.

## Metrics
- Primary metric: EM, using the official TAT-QA scorer with scale.
- Secondary metric: F1.
- Confidence metrics on the shipped confidence: Brier, ECE (10 equal-width bins), AUROC and AURC.

## Abstention (pre-registered, V7)
Fixed before any test500 run, using ONLY TAT-QA train and dev rows (no test_gold, test500 or holdout_v1 id; the fit script refuses them). $0, no model calls.
- Fit: `python -m bench.abstention_fit` → `bench/calib/abstention_v7.json`.
  - train: `tatqa-train-post-agent_mk.jsonl` (n=100, TAT-QA train; sha256 `cc1ba733…f49a`, pre-trace-fix code).
  - dev: `tatqa-fix-agent_mk.jsonl` (n=150, TAT-QA dev; sha256 `3c1577f2…ef67`, trace-fix code).
  - Caveat: dev was used during development (#7/#9), so the dev numbers are optimistic. Only test500 is clean.
- Rule (declared before computing AURC or risk): candidate signals `conf_raw`, `conf_det`, `lex`; pick the lowest pooled AURC; the operating point minimises selective risk subject to coverage ≥ 0.80.
- AURC (pooled train+dev, lower is better): conf_raw 0.484, conf_det 0.605, **lex 0.450**.
- **Signal:** `lex = confidence_det + confidence_raw/100` (deterministic gate/trace confidence first, model self-reported confidence as tie-break; missing → 0). Critic and calibration map OFF.
- **Threshold / operating point:** answer iff `lex ≥ 0.809`, i.e. `confidence_det ≥ 0.8` AND `confidence_raw ≥ 0.9`. Otherwise the agent abstains ("I don't know"). Frozen in `bench/abstention.py`.
- What this gave on train+dev (fit data, not a result): coverage 0.828, selective EM 0.720 (train 0.82 / 0.695, full EM 0.65; dev 0.833 / 0.736, full EM 0.693).
- Reported on test500, whatever the outcome: the full risk-coverage curve and AURC for the shipped arm, plus coverage and selective EM at this single operating point. No other threshold is reported as a result.

## Analysis (`python -m bench.heldout_report`)
- Primary comparison: FREEZE (e.g. `agent_cr`+fixes vs `rag`).
  - Paired exact McNemar on per-item EM, two-sided, α=0.05.
  - Paired bootstrap 95% CI of ΔEM (10,000 resamples, seed 2026).
- Secondary comparisons: all other pairs, reported with Holm correction and labelled exploratory.
- A claim of "better" requires p<0.05 *and* a CI that excludes 0. Otherwise the result is reported as "no detectable difference".
- All results are reported, including null and negative ones.
