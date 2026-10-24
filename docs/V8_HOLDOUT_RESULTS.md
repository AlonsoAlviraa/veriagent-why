# V8 hold-out results (single pre-registered run, no tuning)

- Slice: dev positions 720–1019 (`docs/v71/holdout300.json`), n=300, all rows valid. Same provider/model as V7 (Nebius `nvidia/Nemotron-3_5-Lightning`).
- Frozen before opening: config commit `4e43fbbbe5c9ef963d27280493acf4d7104592d0`, prereg SHA note `2b09c0a39575aaeef26e25e52109da4f8671c7e0`.
  k=5 primary `bench/calib/v8_conf.json` (hash 70926c2c67b1f17a, thr 0.5189); k=0 secondary `v8_conf_k0.json` (hash ceaed3cbc6de5dc4, thr 0.4901).
- Analysis: `bench/v8_holdout.py` (applies frozen weights; no refit). Lex Platt/isotonic baselines fitted on design rows only. Target = V7 official EM. Raw: `docs/v8/holdout_report.json`. Paired bootstrap B=2000, seed 2026.

## Answers (official EM; V7 remains the answer system)
| Arm | EM | F1 | ΔEM vs V7 [95% CI] | fixed/broken | McNemar p | cost USD | calls/item | latency s/item |
|---|---|---|---|---|---|---|---|---|
| V7 | 64.67 | 71.66 | — | — | — | 0.0547 | 2.38 | 3.65 |
| A | 57.33 | 65.69 | −7.33 [−12.33, −2.33] | 20/42 | 0.007 | 0.0733 | 3.38 | 4.75 |
| B | 52.00 | 59.78 | −12.67 [−18.67, −6.67] | 24/62 | 0.0001 | 0.1679 | 8.39 | 10.52 |
| BC | 50.33 | 58.11 | −14.33 [−20.67, −8.33] | 24/67 | <0.001 | 0.1709 | 8.50 | 10.65 |

All V8 answer arms lose to V7, as on design. **V7 stays as the answer system.**

## Confidence / abstention (target: V7 correct)
| Signal | AUROC | AURC | Brier | ECE | coverage @thr | selective EM |
|---|---|---|---|---|---|---|
| **V8 k=5 (primary)** | **0.634** | **0.270** | **0.217** | 0.071 | 83.3% | **68.8%** |
| V8 k=0 (secondary) | 0.622 | 0.286 | 0.217 | 0.065 | 79.3% | 69.8% |
| lex frozen (0.809) | 0.532 | 0.324 | 0.283 | 0.208 | 81.7% | 64.9% |
| lex Platt (design) | 0.532 | 0.324 | 0.231 | 0.034 | — | — |
| lex isotonic (design) | 0.548 | 0.313 | 0.254 | 0.169 | — | — |
| agreement raw | 0.537 | 0.316 | 0.340 | 0.283 | — | — |

Paired Δ (V8 − baseline), 95% CI:

| Comparison | ΔAUROC | ΔAURC | ΔECE |
|---|---|---|---|
| k=5 vs lex frozen | [+0.017, +0.187] | [−0.131, +0.007] | [−0.183, −0.060] |
| k=5 vs lex Platt | [+0.017, +0.187] | [−0.131, +0.007] | [+0.002, +0.107] (Platt better) |
| k=5 vs lex isotonic | [+0.003, +0.169] | [−0.127, +0.015] | [−0.159, −0.011] |
| k=5 vs agreement | [+0.027, +0.170] | [−0.115, +0.007] | [−0.260, −0.146] |
| k=0 vs lex frozen | [−0.002, +0.183] | [−0.119, +0.028] | [−0.163, −0.082] |
| k=0 vs lex Platt | [−0.002, +0.183] | [−0.119, +0.028] | [+0.008, +0.087] (Platt better) |
| k=0 vs lex isotonic | [−0.017, +0.168] | [−0.114, +0.031] | [−0.172, −0.004] |
| k=0 vs agreement | [+0.009, +0.159] | [−0.099, +0.022] | [−0.277, −0.140] |

## Verdict (as pre-registered)
- **Primary (k=5): the discrimination/abstention claim holds on the hold-out.** ΔAUROC CIs exclude 0 against all four baselines (lower bound vs isotonic is only +0.003). The AURC improvement is directionally consistent, but its CIs touch 0, so it is not claimed.
- AUROC dropped from design to hold-out (0.670 → 0.634); lex dropped too (0.575 → 0.532).
- **No calibration claim.** Recalibrated lex (Platt) has a better ECE than V8 (CI excludes 0 in Platt's favour).
- Secondary k=0: it is not significant vs lex (CIs cross 0), only vs raw agreement. So the K=5 samples carry the hold-out gain, at ~3.1× the cost of V7 per item.
- Selective EM at the frozen threshold: 68.8% at 83.3% coverage (k=5), vs lex 64.9% at 81.7%.
- Hold-out cost: ≈ $0.17 (ledger delta). Cumulative Nebius ledger: $7.25 of the $20 budget.
- No tuning was done after opening. test500 was not touched.
