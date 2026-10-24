# V9 final hold-out results (oodsec, single run)

Date: 2026-10-24. Code: `bdcc49d` (clean tree, frozen config hash ee774546ef9ccf14). Set: `oodsec`, 368 questions / 92 tables
from SEC 10-Ks filed 2026-06-01..2026-10-24 (see `docs/V9_FINAL_SET.md`, prereg Amendment 1). Raw analysis output:
`docs/v9/final_oodsec_analysis.json` (produced by `python -m bench.v9_final`, models fitted once on the 600 design rows).

## Run integrity
- Exactly one run of `agent_v9`, 4 deterministic shards (`ids[k::4]` of `docs/v9/final_oodsec.json`), 92 rows each, 368 unique ids.
- 0 error rows, 0 retries, 0 errors/429s in logs. All rows `code_rev=bdcc49d`, `dirty=false`, data sha256 332cd992...
- 1171+ model calls per shard log total; all other arms (V7, V8, lex) are derived from the same traces, no extra runs.
- Nebius spend for this run: ~$0.26 (ledger 7.7512 -> 8.0129 USD cumulative; cap $20).
- No tuning or re-running after seeing results.

## Accuracy
| | EM | F1 |
|---|---|---|
| V7 answer (shared by all arms) | 99.18% (365/368) | 99.18% |
I3b (answer arm): 0 fixed, 0 broken. Errors: 1 arithmetic/text, 2 arithmetic/table-text.

## Confidence / selective prediction (selective EM at lex_frozen coverage 78.26%)
| Arm | AUROC | ECE | Brier | AURC | Coverage | Sel. EM | Cost $/368 | calls/item |
|---|---|---|---|---|---|---|---|---|
| lex frozen (thr 0.809) | 0.633 | 0.246 | 0.095 | 0.0085 | 0.783 | 0.993 | 0.056 (V7) | 2.66 |
| lex platt (orig. H1 base) | 0.633 | 0.355 | 0.135 | 0.0085 | 0.783 | 0.993 | 0.056 | 2.66 |
| V8 refit | 0.809 | 0.373 | 0.163 | 0.0020 | 0.783 | 0.997 | 0.172 | 9.0 |
| V9 cheap | 0.815 | 0.273 | 0.098 | 0.0018 | 0.783 | 0.997 | 0.068 | 3.66 |
| V9 full | 0.816 | 0.252 | 0.087 | 0.0018 | 0.783 | 0.997 | 0.260 | 13.0 |
| (ref) raw MSP | 0.745 | 0.099 | 0.043 | 0.0025 | 0.783 | 0.993 | - | - |

## Pre-registered tests (item bootstrap 2000, seed 2026; table-cluster bootstrap)
| Test | dAUROC 95% CI (item / cluster) | -dECE CI | -dAURC CI | Verdict |
|---|---|---|---|---|
| P1 V9 cheap vs lex frozen | [-0.010, 0.493] / [-0.005, 0.495] | [-0.044, -0.011] | [-0.000, 0.015] | **Not supported.** AUROC CI includes 0; ECE significantly *worse* than lex frozen |
| P2 V9 full vs V8 refit | [-0.075, 0.074] / [-0.076, 0.078] | [0.109, 0.132] | [-0.001, 0.001] | AUROC: no difference. ECE: significantly better |
| H1-orig V9 cheap vs lex platt | [-0.010, 0.493] | [0.070, 0.094] | [-0.000, 0.015] | AUROC n.s.; ECE better |
| V9 cheap vs V8 refit (sec.) | [-0.086, 0.094] | [0.081, 0.117] | | ECE better at ~40% of V8 cost |
| V9 full vs lex frozen (sec.) | [0.000, 0.507] | [-0.021, 0.008] | | borderline AUROC, ECE n.s. |

## Conformal risk control (alpha = 0.10, threshold calibrated on design, transferred unchanged)
| Arm | lambda | Realized risk (answered & wrong) | Coverage | Sel. EM |
|---|---|---|---|---|
| lex platt | inf | 0.000 | 0.000 | - |
| V8 refit | 0.697 | 0.000 | 0.345 | 1.000 |
| V9 cheap | 0.694 | 0.000 | 0.641 | 1.000 |
| V9 full | 0.683 | 0.003 | 0.745 | 0.996 |

**Threshold transfer outcome:** all design-calibrated thresholds stayed valid on this OOD set (risk <= 0.10 for every arm), but
this is trivially easy here: the base error rate is 0.8%, so even answering everything has risk 0.008. The transferred thresholds
are therefore very *conservative*: they abstain on 25-65% of items that are ~99% correct (lex platt abstains on everything).
Risk control transferred; efficiency did not.

## Honest reading (including negatives)
1. **Ceiling effect dominates.** With only 3 wrong answers out of 368, AUROC is estimated from 3 positives; CIs span ~0.5. The set
   cannot discriminate between confidence methods. This is the main limitation of the final test.
2. **Primary P1 fails.** V9 cheap does not significantly beat lex frozen on AUROC, and is significantly worse on ECE.
3. **Primary P2: mixed.** No AUROC gain over V8 refit; clear calibration (ECE, Brier) gain.
4. Calibration of all fitted models degraded vs design (ECE 0.25-0.37): they were fitted where error rates were much higher, so they
   are under-confident on this easy OOD set. Raw MSP is best calibrated here (ECE 0.099), which we did not pre-register.
5. Point estimates are consistent with design (V9 ~ V8 > lex on AUROC/AURC; V9 cheap at ~40% of V8 cost), but are not significant.
6. Accuracy 99.2% is not comparable to TAT-QA numbers (templated, programmatic questions; see V9_FINAL_SET.md residual risks).

## Decision points (not taken by us)
- Whether to report V9 as "no significant gain on the final hold-out" (what the pre-registration implies) - we recommend yes.
- Any harder OOD set would be a new, separately pre-registered experiment, not a re-run of this one.
