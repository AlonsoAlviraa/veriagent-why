# Audit of the audit.json traces: VeriAgent Why

Generated 2026-10-23 by `audit_traces.py`, a deterministic script that makes **no LLM calls and costs $0**. Per-trace labels are in `trace_labels.csv` (2,415 traces: every `*.audit.json` under `bench/results/traces/<run>/`).
Dev/eval traces were only **read** to diagnose problems. Nothing was tuned on them. Rule-based stage labels approximate the root cause, so take them as approximations.

## 1. Failure taxonomy by stage: the 5 verify-v2 configs (TAT-QA dev 150, InsightBench 70)
InsightBench "correct" means judge >= 0.5. Each failed item gets the first matching stage, in this order: sql (>= half the queries are errors), retrieval_empty (>= half the results are empty), claim gate dropped everything, writer unfaithful (faithfulness < 0.5), writer off-goal (faithful but the judge scores it low).

| stage | agent_mk | agent_vr | agent_pot | agent_sc | agent_cr |
|---|---|---|---|---|---|
| calc_arithmetic | 3 | 10 | 2 | 3 | 1 |
| correct | 106 | 79 | 102 | 100 | 110 |
| post_format_rounding | 0 | 11 | 0 | 0 | 0 |
| route | 0 | 0 | 1 | 1 | 0 |
| writer_count | 3 | 4 | 3 | 4 | 1 |
| writer_magnitude | 0 | 3 | 0 | 0 | 1 |
| writer_scale | 6 | 10 | 16 | 6 | 6 |
| writer_sign | 1 | 1 | 3 | 3 | 1 |
| writer_span | 31 | 32 | 23 | 33 | 30 |

| label | agent_mk | agent_vr | agent_pot | agent_sc | agent_cr |
|---|---|---|---|---|---|
| arithmetic_wrong_operands_or_formula | 3 | 10 | 2 | 3 | 1 |
| calc_loop_repeats_same_expr | 31 | 0 | 31 | 31 | 31 |
| correct_but_gate_failed | 10 | 0 | 4 | 8 | 10 |
| count_wrong | 3 | 4 | 3 | 4 | 1 |
| critic_revised | 0 | 0 | 40 | 0 | 48 |
| gate_accepted_wrong_answer | 40 | 0 | 43 | 41 | 33 |
| invalid_citations | 47 | 78 | 53 | 51 | 52 |
| magnitude_x100_x1000 | 0 | 3 | 0 | 0 | 1 |
| overconfident_wrong(conf>=0.7) | 38 | 55 | 33 | 37 | 14 |
| post_format_changed_score_helped | 58 | 44 | 50 | 54 | 60 |
| post_format_changed_score_hurt | 2 | 1 | 3 | 2 | 2 |
| rounding_or_precision | 0 | 11 | 0 | 0 | 0 |
| route_EVIDENCE_on_arithmetic | 0 | 0 | 1 | 1 | 0 |
| scale_mismatch | 6 | 10 | 16 | 6 | 6 |
| sign_error | 1 | 1 | 3 | 3 | 1 |
| underconfident_correct(conf<=0.3) | 10 | 0 | 13 | 9 | 10 |
| wrong_span | 7 | 7 | 3 | 10 | 6 |
| wrong_span_partial | 24 | 25 | 20 | 23 | 24 |

| stage | agent_mk | agent_vr | agent_pot | agent_sc | agent_cr |
|---|---|---|---|---|---|
| correct | 20 | 15 | 14 | 20 | 22 |
| retrieval_empty | 3 | 3 | 2 | 4 | 5 |
| sql | 6 | 5 | 8 | 6 | 6 |
| writer_unfaithful | 15 | 11 | 17 | 14 | 8 |
| writer_wrong_insight(faithful_but_off_goal) | 26 | 27 | 29 | 26 | 29 |

| label | agent_mk | agent_vr | agent_pot | agent_sc | agent_cr |
|---|---|---|---|---|---|
| critic_revised | 0 | 0 | 0 | 0 | 66 |
| empty_sql_result | 17 | 18 | 17 | 22 | 17 |
| kept_claim_without_citation | 3 | 10 | 1 | 3 | 1 |
| no_claims_kept | 1 | 0 | 1 | 0 | 1 |
| overconfident_wrong(conf>=0.7) | 41 | 33 | 45 | 3 | 8 |
| requery_STOP_sufficient_despite_empty_or_error | 15 | 0 | 13 | 13 | 12 |
| sql_error_in_evidence | 15 | 16 | 15 | 18 | 18 |
| sql_repair_same_error | 13 | 0 | 12 | 15 | 12 |
| unsupported_numbers_kept | 2 | 2 | 6 | 5 | 4 |

Takeaways:
- **TAT-QA:** wrong spans are **74% of the remaining failures in agent_cr** (30 of 40). Of those 30, 18 are truncated sub-spans, 7 add extra words, 2 are multi-span mismatches and 3 are other. Scale is next (6). True arithmetic errors are almost gone (1). The gold-derived labels (span / scale / count / arithmetic) are computed by the audit and never reached a model.
- **agent_vr** brings back failure classes the controller had fixed: rounding/precision 11 (0 for mk), arithmetic 10 (3 for mk), magnitude 3. The verify path skips both the calc loop and post-format rounding.
- **agent_pot** triples scale errors (16 vs 6). When the program recomputes a value, it rewrites the scale.
- **InsightBench:** most failures come from the writer going off-goal while staying faithful (26–29 per config). SQL and empty retrieval cause about 10 per config. The claim gate is not the bottleneck.

## 2. Recurring error patterns (examples)
1. **The calc loop repeats the same expression up to 3 times.** 31/150 in every NUMERIC config, roughly 2 wasted calls each. The controller never stops once the observation is stable. Examples: `bench/results/traces/tatqa-post-agent_mk/agent_mk/06dfc869-b3e2-446e-9b9a-1b2374c63c04.audit.json`, `.../078e34fa-b33a-43fe-afd3-d39b4cbd6a6b.audit.json`, `.../12005950-7f78-497e-a1b4-cfc8c7389aa1.audit.json`.
2. **The Claim Gate ACCEPTs wrong answers.** mk 40, cr 33, pot 43, sc 41. The gate checks that the answer is traceable, not that it is correct, so spans and scales slip through. Examples: `tatqa-post-agent_mk/agent_mk/0747c0e5-...`, `0f5bcfe8-...`, `1047c8b7-...`. In 1047c8b7 the gold answer is a sentence and the answer given is "30".
3. **Truncated span answers.** The writer trims the gold sentence, and EM requires all of it. Examples: cr `0747c0e5-2b69-414b-a922-ffa20be13aa1`; `ec290759-3e73-4ee3-9950-c3f0a2609da1` (cr *revised* a correct full span into a truncated one: the only cr loss).
4. **Overconfidence.** TAT-QA wrong answers with conf >= 0.7: mk 38, vr 55, cr 14. InsightBench mk has mean confidence 0.757 and accuracy 0.286. Its formula is `min(0.9, 0.2+0.7*sql_ok*kept)` and never looks at whether the content answers the goal. Examples: `insightbench-post-agent_mk/agent_mk/flag-1`, `flag-12`, `flag-14`.
5. **Requery STOPs with the reason "evidence sufficient (>=5 successful queries, 0 errors)" even when results are empty.** This happens in 12–15 traces per Markov config. Empty result sets count as successes. In `insightbench-post-agent_vr/agent_vr/flag-1` and `insightbench-post-agent_mk/.../flag-1`, q2, q3 and q6 returned 0 rows, yet the writer still states "150 open incidents". Also `flag-14`, `flag-15`.
6. **SQL repair reproduces the same error.** 251 `GIVE_UP` decisions say "repair reproduced the same error", against 653 REPAIR attempts. The repair prompt does not change the failing construct. Examples: `insightbench-post-agent_mk/agent_mk/flag-34`, `flag-39`, `flag-80`.
7. **The InsightBench gate keeps claims that contradict their own evidence.** In `insightbench-v2-agent_cr/agent_cr/flag-1`, c1 says Hardware has "the longest resolution time 7.36". Its cited q3 shows Inquiry/Help at 8.51. Every number appears in the evidence, so the claim is KEPT, and the critic missed it too. The gate checks numbers but not comparatives such as "longest", "highest" or "most".
8. **Scale and magnitude.** Examples: `tatqa-post-agent_mk/agent_mk/0f5bcfe8-...`, `3bc9ea91-...`, `4a58213e-...`. Post-format *hurts* 2–3 items per config (0f5bcfe8, 4a58213e) and helps 50–60.
9. **Kept claims with no citation** (mostly baselines): react 63, rag 45, agent 17, vr 10, mk 3. Examples: `insightbench-post-agent_mk/agent_mk/flag-60`, `flag-90`, `flag-92`.

## 3. Bugs in the traces and logging
| Bug | Traces affected | Example |
|---|---|---|
| `scores.failure` is null everywhere: the failures_all join never matches the post/v2 runs | **2,415 / 2,415** | any |
| agent_vr traces have only plan, post_format and scoring. There are **no verify_retry_attempt, claim_gate or route steps**, so the verify flow is invisible | 311 (vr TAT dev 150, train 100, IB 61) | `tatqa-post-agent_vr/agent_vr/*` |
| Confidence: `deterministic` does not match the recomputed value from the stated formula. The formula string was not updated for vr/cr/sc/pot, which blend in the verifier or critic. vr: 149/150 (e.g. 0.733 logged vs 0.2 recomputed) | 883 | `insightbench-post-agent_vr/agent_vr/flag-10` |
| `models[]`: the Super verifier is labelled `generator`; the cr critic and sc adjudicator have no `verifier` role (their calls only appear in `llm_calls` as v2_critic / v2_adjudicate) | 311 mislabelled; 517 missing role | `tatqa-v2-agent_cr/agent_cr/*` |
| The plain `agent` config logs decisions with `decision: null`. Its "STOP" means "no retry needed", so it reads like a gate failure (89 correct items look like "gate failed") | 250 | `tatqa-post-agent/agent/01c49bda-...` |
| TAT-QA rag, react and vr have no claim_gate step | 550 | `tatqa-post-rag/*` |
| InsightBench `dataset_split` is not_logged, so tune-30 and eval-70 traces can't be told apart in the trace | 631 | any IB |
| `insightbench-post-agent` lists no judge in models[] on 1 trace (69/70), although the score is present | 1 | see CSV |
| The `explain.citations_valid` metric flags valid TAT cells as invalid even on correct answers (e.g. 4 cited / 2 valid) | 47–98 per config | `tatqa-v2-agent_cr/.../06dfc869-...` |
| Decisions contradict outcomes: requery "evidence sufficient" with empty results (#5); gate ACCEPT on wrong answers (#2); 10 correct mk items end with gate STOP (correct but conf 0.2) | see above | |
| RAG on InsightBench has no SQL, so every trace gets the "empty_sql_result" label. This is a quirk of my labelling, not a real failure | 70 | |
| No secrets: `redactions` = 0 in the index | – | |

## 4. agent_cr vs agent_mk: where cr wins and loses
- **TAT-QA dev:** 110 vs 106, from 5 wins and 1 loss. Only **2 wins come from the critic's revision** (1148519a, 3d384cee: count 3→1). The other 3 wins (1e20b997, 69b61533, de34ea96) had **no revision**: they are sampling noise from the generator. mk and mknv, essentially the same pipeline, already flip 6 items on their own. The only loss (ec290759) was a revision that truncated a correct span. **The net effect of the critic is +1 item. The +4 is within the noise.**
- Of the 48 revised items, 24 stayed correct, 21 stayed wrong, 2 were fixed and 1 broke. The critic rarely changes the outcome. Its real value is **calibration**: overconfident wrong answers fell from 38 to 14, and mean confidence went from 0.73 to 0.61 at 0.73 accuracy.
- **InsightBench:** 11 wins and 14 losses (judge delta > 0.15). Several losses (flag-28, flag-35) are retrieval_empty in cr but not in mk. That is SQL non-determinism, not the critic. The judge is noisy too: between mk and mknv the mean absolute difference is 0.136 and 18/70 items move >= 0.3. Differences under about 0.05 on the average are not signal. Overconfident wrong answers: 41 → 8.

## 5. Fixes ranked by estimated impact (items affected; estimates)
1. **Span answers: extract the full sentence/clause and never revise to a substring.** Up to 25 of 40 cr TAT failures (18 truncated + 7 superset). Potential +10–20 EM. Tune on train only.
2. **InsightBench requery: count empty results as gaps and re-plan.** 12–15 items per config; also cuts claims that describe empty queries.
3. **InsightBench gate: check comparatives/superlatives against the cited table (deterministic argmax/argmin).** Catches pattern #7. Expected to raise faithfulness and the judge score on the 26–29 off-goal items.
4. **InsightBench confidence: add goal coverage and gate quality, or use the critic's p_correct calibrated on the 30 tuning tasks.** Fixes the 0.76-confidence / 0.29-accuracy gap (≈40 overconfident items in mk).
5. **SQL repair: pass the previous failed SQL plus the error class and forbid the same construct; switch to a simpler query after the first repeat.** 251 GIVE_UPs; about 6 items per config fail at the SQL stage.
6. **Calc loop early stop when an observation repeats.** 31 items, about 60 calls saved per 150. No accuracy change, lower cost and latency.
7. **Scale rule: keep the scale of the source cell; pot must not rewrite it.** 6–16 items.
8. **Logging fixes (no accuracy impact, needed for review):** failure join (2,415), vr steps (311), roles in models[] (828), formula strings (883), IB split field (631), named decisions for the agent config (250).
9. **Evaluation: run seeds/repeats or a paired bootstrap before claiming the cr gain.** Generator noise is about 6 items per 150 on TAT-QA and judge noise about 0.14 per item on InsightBench.
