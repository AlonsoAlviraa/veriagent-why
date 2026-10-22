# Eval results: dev split, provider `nvidia`

Measured by `eval/eval.py` on seeded synthetic data. Metric: exact match of `top_cause_label`.

| System | Correct |
|---|---|
| VeriAgent Why | 14/22 (Wilson 95% CI 0.43–0.80) |
| Plain-RAG baseline | 11/22 (Wilson 95% CI 0.31–0.69) |

Secondary metrics (agent): segment match 12/13, secondary cause detected 1/3, secondary false positives 0/19.

Agent model calls: 570 ok, 18 failed (those steps fell back to the deterministic rules). Baseline model errors (scored wrong): 3.

| qid | kind | expected | agent | baseline |
|---|---|---|---|---|
| q01 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q02 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q03 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q04 | breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q05 | negative_control | none | carrier_sla_breach | carrier_sla_breach |
| q06 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q25 | seasonality | seasonality | carrier_sla_breach | carrier_sla_breach |
| q26 | seasonality | seasonality | carrier_sla_breach | error |
| q27 | promotion_effect | promotion_effect | carrier_sla_breach | carrier_sla_breach |
| q28 | promotion_effect | promotion_effect | carrier_sla_breach | carrier_sla_breach |
| q29 | noisy_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q30 | noisy_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q31 | multi_cause | carrier_sla_breach | carrier_sla_breach | error |
| q32 | multi_cause | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q33 | noisy_breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q34 | noisy_negative_distractor | none | seasonality | carrier_sla_breach |
| q35 | noisy_seasonality | seasonality | carrier_sla_breach | carrier_sla_breach |
| q36 | noisy_promotion_effect | promotion_effect | carrier_sla_breach | carrier_sla_breach |
| q37 | weak_noisy_breach | carrier_sla_breach | carrier_sla_breach | error |
| q38 | close_multi_cause | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q39 | breach_inside_broad_rise | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q40 | noisy_negative_heavy_missing | none | none | carrier_sla_breach |

## Run notes (22 Oct 2026, 18:25–19:15 Madrid)
- Models: `nvidia/nemotron-3.5-super-vl-120b-a12b` (S2) and `nvidia/nemotron-3.5-lightning-30b-a3b` (S1), both with `enable_thinking: false`, NVIDIA free endpoint, client pacer 1.6 s, retries on 429/5xx, MODEL_TIMEOUT_S=90. Dev split only; test_v2 was not touched.
- Time per question (agent + baseline): median 120 s, p90 214 s, total 49 min for 22 questions.
- The 18 failed agent calls were read timeouts (mostly the S2 Cause Analyst / Writer). Those steps used the deterministic rules. The 3 baseline errors were timeouts/500s and are scored as wrong.

## Why the live agent scored below the sample-mode rules (21/22)
All 8 misses predict `carrier_sla_breach` (or `seasonality` for q34). Reading the traces:
1. **The Evaluator's model verdict overrode the SQL verdict.** Lightning answered "supports" for single-dimension carrier/region hypotheses, where the deterministic rule had said refutes/gap (broad seasonal rises, promotion-driven rises, negative controls). The drill-down then found a "carrier x region" segment, so the run was labelled carrier_sla_breach.
2. **The Planner's model choice dropped rival hypotheses.** For example q25 picked only `H_carrier`, `H_region`, so `H_seasonal` was never tested. The prompt allowed 2–3 hypotheses, while the design says 3–5 competing ones.
3. The Cause Analyst's label was taken from the model even when it named a cause that no supported hypothesis backs.
Fixes are on branch `feat/e2e` (PR #2). Any re-run on dev after those fixes is **in-sample**, because the fixes were derived from these dev traces.
