# V10 results — hard sets (MultiHiertt, DocFinQA)

Status: **PARTIAL** under the pre-registered §5 rule (docs/V10_PREREG.md). Raw output: `docs/v10/results_v10.json`, produced by
`python -m bench.v10_analysis /workspace/v10-hard/runs "/workspace/v9-eval/r1_s*.jsonl" /workspace/v9-eval/final_oodsec.jsonl`.

## Run facts
- 12 shards, 1600 rows (400 items x 2 systems: agent_v9, plain RAG), all shards finished (SHARDDONE). Rows carry code_rev 0b7aac6, dirty=false.
- 11 rows errored and are excluded: agent_v9 5 (MultiHiertt) + 5 (DocFinQA), RAG 1 (DocFinQA). They were not re-run.
- Split coverage: MultiHiertt test 300/304, cal 95/96; DocFinQA test 296/298, cal 99/102. The script therefore reports `complete: false`.
- Spend: Nebius ledger $13.65 after the runs (below the $15 prereg stop; hard cap $20 not approached).

## Disclosures (deviations from the frozen script)
1. Full runs were launched ~12:24 Madrid, before commit 33d1e93 froze §7 (already disclosed in V10_PREREG §7).
2. Two mechanical fixes to `bench/v10_analysis.py` (commit 769e39d) after a smoke run on partial rows, before seeing final numbers: `operands_in_context` is read from the document `source` field (strata were empty), and completeness is checked against split coverage (it wrongly said complete). No metric, threshold or signal changed.

## Answer accuracy (semantic, test split)
| Set | V7 agent | plain RAG | "not hard" (>60%)? |
|---|---|---|---|
| MultiHiertt | 48.67% (n=300; EM 2.33%) | 15.0% | no — hard |
| DocFinQA | 48.65% (n=296; EM 35.14%) | 18.31% (n=295) | no — hard |

## Confidence signals (test, error = semantic wrong)
| Set | Signal | AUROC [95% item CI] | AURC | ECE | CRC α=0.10 cal-refit risk / coverage |
|---|---|---|---|---|---|
| MultiHiertt | V9_full | 0.674 [0.612, 0.736] | 0.409 | 0.106 | 0.077 / 0.203 ✅ |
| MultiHiertt | V9_cheap | 0.651 [0.588, 0.715] | 0.428 | 0.082 | 0.113 / 0.293 |
| MultiHiertt | V8_refit | 0.646 [0.583, 0.707] | 0.404 | 0.064 | 0.090 / 0.280 |
| MultiHiertt | raw token prob | 0.622 [0.558, 0.684] | 0.449 | 0.287 | 0.130 / 0.310 |
| MultiHiertt | lex_frozen | 0.574 [0.513, 0.640] | 0.475 | 0.253 | 0.113 / 0.243 |
| DocFinQA | V9_full | 0.655 [0.594, 0.715] | 0.423 | 0.133 | **0.179** / 0.416 ❌ |
| DocFinQA | V9_cheap | 0.623 [0.565, 0.687] | 0.463 | 0.083 | 0.145 / 0.324 |
| DocFinQA | V8_refit | 0.633 [0.570, 0.696] | 0.403 | 0.051 | 0.139 / 0.355 |
| DocFinQA | raw token prob | 0.650 [0.590, 0.711] | 0.387 | 0.338 | 0.095 / 0.270 |
| DocFinQA | lex_frozen | 0.589 [0.527, 0.651] | 0.421 | 0.230 | 0.047 / 0.139 |

## §5 decision for V9_full
- AUROC lower bound > 0.5: MultiHiertt 0.612 ✅, DocFinQA 0.594 ✅.
- Cal-refit CRC risk ≤ α+0.03 = 0.13: MultiHiertt 0.077 ✅, DocFinQA 0.179 ❌.
- → **PARTIAL**. The 6 missing DocFinQA items cannot bring 0.179 under 0.13, so the label does not depend on the errored rows.

## Paired AUROC differences (item bootstrap, 95% CI)
| Comparison | MultiHiertt | DocFinQA |
|---|---|---|
| V9_full − lex_frozen | [+0.024, +0.168] **better** | [+0.007, +0.124] **better** |
| V9_full − V9_cheap | [−0.022, +0.071] n.s. | [−0.007, +0.067] n.s. |
| V9_full − raw token prob | [−0.010, +0.116] n.s. | [−0.072, +0.079] n.s. |

## Negatives (honest)
- V9_full beats only the lexical baseline; it is **not** better than V9_cheap or raw answer-token probability on either set.
- CRC with the design-fitted threshold fails on both sets for V9_full (realized risk 0.107 on both, α=0.10). Even refit on cal fails on DocFinQA.
- Coverage at 10% selective risk is ~0 for every signal on both sets.
- P(true)-only is uninformative on MultiHiertt (AUROC 0.543, CI includes 0.5).
- MultiHiertt EM is 2.33% vs 48.67% semantic: official EM is near-useless as a label here.

## DocFinQA operands_in_context abstention breakdown
| operands in context | n | V7 semantic acc | AUROC V9_full | AUROC lex_frozen | AUROC raw prob | abstain V9_full (design CRC) | abstain lex_frozen |
|---|---|---|---|---|---|---|---|
| True | 208 | 66.8% | 0.652 | 0.550 | 0.656 | 69.7% | 61.1% |
| False | 88 | 5.7% | 0.757 | 0.651 | 0.742 | 80.7% | 71.6% |

When operands are missing from the retrieved context the agent is almost always wrong (5.7%), and V9_full abstains more (80.7%), but it still answers ~19% of those items, which are nearly all errors.

## Cost per item (test)
| Set | V7 | V9_cheap | V8_refit | V9_full |
|---|---|---|---|---|
| MultiHiertt calls / sec | 3.42 / 12.0 | 4.42 / 13.4 | 9.72 / 30.6 | 13.75 / 39.0 |
| DocFinQA calls / sec | 3.51 / 11.8 | 4.51 / 13.6 | 9.80 / 24.7 | 13.81 / 36.4 |
