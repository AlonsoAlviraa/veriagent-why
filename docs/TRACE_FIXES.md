# Trace-audit fixes

Fixes for every problem found in the audit of `*.audit.json` traces. Each fix has a regression test in
`tests/test_trace_fixes.py` built from real trace snippets, so the failure mode cannot silently return.

| # | Problem in traces | Fix | Where | Test |
|---|---|---|---|---|
| 1 | Truncated spans (`ec290759`), merged year lists | Critic asks for the complete span; `split_years` post-rule; `span_extend` available but **off** (no gain on TRAIN replay) | `fixes.py`, `verify2.py`, `tatqa.py` | `test_truncated_revision_rejected_ec290759`, `test_span_mode_off_and_split_years` |
| 2 | Empty SQL results cited as evidence (flag-1 q5) | Empty/error results marked `NO EVIDENCE`, not valid sources; evaluator "sufficient" overridden when 0 usable results | `insightbench.py`, `fixes.py` | `test_empty_result_is_gap_flag1`, `test_requery_never_sufficient_with_empty`, `test_gate_does_not_cite_empty_results` |
| 3 | Contradicted comparatives / superlatives passed the gate (flag-1 q3) | `check_comparatives` in the IB gate; contradicted claims dropped with feedback | `fixes.py`, `insightbench.py`, `verify2.py` | `test_ib_v2_gate_drops_contradiction` |
| 4 | Uncalibrated critic confidence | Isotonic map fitted **only** on TAT-QA train and the 30 InsightBench TUNE tasks; split asserted at fit time | `scripts/fit_trace_fixes.py`, `bench/calib/`, `confidence.py` | `test_isotonic_monotone_and_train_only`, `test_calibration_files_declare_split` |
| 5 | SQL repair blind to its own failures, repeated identical SQL (flag-34) | Repair prompt gets failed SQL + error; identical normalized SQL ⇒ `GIVE_UP` without re-running | `insightbench.py`, `fixes.sql_key` | `test_sql_repair_stops_on_identical_repeat_flag34`, `test_repair_prompt_carries_failed_queries` |
| 6 | Wasted compute | Calc-step dedup + early stop, per-item LLM cache at temperature 0, revise only when p < threshold, max-call assertions in tests | `tatqa.py`, `llmio.py`, `verify2.py` | `test_calc_step_stops_on_repeat_06dfc869`, `test_agent_mk_max_calls_with_repeating_calc`, `test_ib_agent_mk_max_calls_offline`, `test_tat_cr_skips_revision_when_not_used`, `test_meter_cache_identical_calls` |
| 7 | PoT / critic rewrote the source scale (×10^k) | `revision_guard`: rejects shorter spans, magnitude rewrites and scale changes when the source states the scale | `fixes.py`, `verify2.py` | `test_magnitude_and_scale_guard_pot` |
| 8 | Trace logging bugs (missing decisions, verifier roles, IB split, confidence not recomputable, retry steps) | Named decisions, roles from calls, `dataset_split`, `confidence` block with `formula_id`/`recomputed`/`matches_logged`, `verify_retry_attempt` steps | `audit_trace.py`, schema | `test_generated_traces_validate_schema`, `test_confidence_formula_matches_logged`, `test_ib_split_field`, `test_citations_valid_table_cells` |
| 9 | No paired significance | Paired bootstrap + exact McNemar | `stats.py`, `scripts/compare_fix.py` | `test_paired_stats` |

## Rules kept
- No tuning on TAT-QA dev or the 70 InsightBench eval tasks (`assert_split` refuses otherwise).
- `CR_ALWAYS_REVISE=1` restores the old always-revise behaviour; `LLM_CACHE=0` disables the cache.

## Known caveats
- `span_extend` gave no EM gain on TRAIN, so it ships disabled; only the year split is active.
- Post-format `infer_scale` still hurts a couple of TAT items (e.g. `0f5bcfe8`, `4a58213e`) while helping many more; left unchanged. The scale guard only covers critic/PoT revisions.
- InsightBench judge scores are noisy at n=70; read the paired tests, not just the means.

## Results (Nemotron-3.5-Lightning via Nebius; TAT-QA dev 150, InsightBench eval 70)
Paired tests vs the previous `agent_mk` (`*-post-agent_mk`). Round spend: $0.53 (calibration + 4 reruns).

| Run | EM / judge mean | F1 / judge>=0.6 | ECE | calls/item | USD | Δ vs prev mk (95% CI, p boot / McNemar) |
|---|---|---|---|---|---|---|
| TAT mk prev | 0.707 | 0.826 | 0.146 | 2.36 | 0.028 | - |
| TAT mk fix | 0.693 | 0.811 | 0.097 | 2.16 | 0.026 | -0.013 [-0.047, 0.020], 0.55 / 0.69 |
| TAT cr prev | 0.733 | 0.851 | 0.126 | 3.79 | 0.046 | +0.027 [0.000, 0.060], 0.13 / 0.22 |
| TAT cr fix | 0.693 | 0.811 | **0.070** | 3.20 | 0.037 | -0.013 [-0.047, 0.020], 0.54 / 0.69 |
| IB mk prev | 0.370 | 0.257 | 0.532 | 4.63 | 0.116 | - |
| IB mk fix | 0.354 | 0.243 | 0.451 | 5.33 | 0.143 | -0.016 [-0.063, 0.033], 0.52 / 1.0 |
| IB cr prev | 0.366 | 0.271 | 0.313 | 6.71 | 0.162 | -0.004 [-0.053, 0.044], 0.86 / 1.0 |
| IB cr fix | 0.346 | 0.200 | **0.138** | 7.04 | 0.174 | -0.024 [-0.077, 0.031], 0.39 / 0.50 |

No accuracy change is statistically significant. The fixes improve calibration (ECE) and cut TAT-QA calls (-8 to -16%).
InsightBench uses more calls (+5 to +15%) because empty or error results now trigger a requery instead of being cited.
TAT `agent_cr fix` matches `agent_mk fix` item for item: with revise-only-when-uncertain plus the revision guard, the critic made no revisions that changed the answer, so the earlier +2.7 pt from always revising is gone (that gain was not significant either).
