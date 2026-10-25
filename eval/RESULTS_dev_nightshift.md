# Eval results: dev split, provider `nightshift`

Measured by `eval/eval.py` on seeded synthetic data. Metric: exact match of `top_cause_label`.

| System | Correct |
|---|---|
| VeriAgent Why | 21/22 (Wilson 95% CI 0.78–0.99) |
| Plain-RAG baseline | 12/22 (Wilson 95% CI 0.35–0.73) |

Secondary metrics (agent): segment match 11/13, secondary cause detected 1/3, secondary false positives 0/19.

Agent model calls: 111 ok, 225 failed (those steps fell back to the deterministic rules). Baseline model errors (scored wrong): 0.

| qid | kind | expected | agent | baseline |
|---|---|---|---|---|
| q01 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q02 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q03 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q04 | breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q05 | negative_control | none | none | carrier_sla_breach |
| q06 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q25 | seasonality | seasonality | seasonality | carrier_sla_breach |
| q26 | seasonality | seasonality | seasonality | none |
| q27 | promotion_effect | promotion_effect | promotion_effect | carrier_sla_breach |
| q28 | promotion_effect | promotion_effect | promotion_effect | carrier_sla_breach |
| q29 | noisy_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q30 | noisy_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q31 | multi_cause | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q32 | multi_cause | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q33 | noisy_breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | none |
| q34 | noisy_negative_distractor | none | none | carrier_sla_breach |
| q35 | noisy_seasonality | seasonality | seasonality | carrier_sla_breach |
| q36 | noisy_promotion_effect | promotion_effect | promotion_effect | carrier_sla_breach |
| q37 | weak_noisy_breach | carrier_sla_breach | none | carrier_sla_breach |
| q38 | close_multi_cause | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q39 | breach_inside_broad_rise | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q40 | noisy_negative_heavy_missing | none | none | carrier_sla_breach |

## Run notes (25 Oct 2026, Meterless Nightshift 1.2.7)
- Provider: `nightshift` (Meterless Nightshift 1.2.7 local runtime on `127.0.0.1:8088/v1`), routing S1 to `nvidia/nemotron-3.5-lightning-30b-a3b` (`enable_thinking=false`, `reasoning_effort=none`) and S2 to `nvidia/nemotron-3-ultra-550b-a55b` (`enable_thinking=false`), `ZETARIS_BACKEND=sample` (synthetic DuckDB datasets), `SAMPLE_MODE=false`, `LLM_FALLBACK=none`.
- Score: **VeriAgent Why 21/22 (95.5%, Wilson 95% CI 0.78–0.99)** vs **Plain-RAG baseline 12/22 (54.5%, Wilson 95% CI 0.35–0.73)**. The single miss is `q37` (`weak_noisy_breach`, where the agent abstained/`none` with confidence 20).
- Honest caveats:
  1. **In-sample re-run:** As noted in `eval/RESULTS_dev_nvidia.md`, the guardrails in `app/agents/core.py` (preventing the S1 evaluator from overriding SQL refutations into `supports` and keeping rival hypotheses `H_promo` / `H_seasonal` in the plan) were introduced in PR #2 after inspecting the 22 Oct dev traces (`14/22`). Therefore this `21/22` dev score is an in-sample verification of those fixes, not an out-of-sample evaluation.
  2. **Nightshift 502 fallback:** Under burst S1 calls (`s1_filter` parallel batching), Nightshift returned `HTTP 502: Bad Gateway` on 225 of 336 agent model calls (111 succeeded across Planner, Retriever, S1 Filter, Evaluator, Cause Analyst and Writer); failed steps fell back to the deterministic rules as designed. All 22 Plain-RAG baseline calls (1 S2 Ultra call per question) succeeded with 0 errors.
