# Eval results: dev split, provider `nightshift`

Measured by `eval/eval.py` on seeded synthetic data. Metric: exact match of `top_cause_label`.

| System | Correct |
|---|---|
| VeriAgent Why | 21/22 (Wilson 95% CI 0.78–0.99) |
| Plain-RAG baseline | 12/22 (Wilson 95% CI 0.35–0.73) |

Secondary metrics (agent): segment match 11/13, secondary cause detected 1/3, secondary false positives 0/19.

Agent model calls: 405 ok, 3 failed (99.3% live model completion; 19/22 questions had 0 failed calls; the 3 failed calls fell back to the deterministic rules). Baseline model errors (scored wrong): 0.

| qid | kind | expected | agent | baseline |
|---|---|---|---|---|
| q01 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q02 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q03 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q04 | breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q05 | negative_control | none | none | carrier_sla_breach |
| q06 | carrier_breach | carrier_sla_breach | carrier_sla_breach | carrier_sla_breach |
| q25 | seasonality | seasonality | seasonality | carrier_sla_breach |
| q26 | seasonality | seasonality | seasonality | carrier_sla_breach |
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

## Run notes & caveats
- **Provider & pinned models:** Meterless Nightshift 1.2.7 (`http://127.0.0.1:7777/v1`) routing S1 (`retriever`, `s1_filter`, `evidence_evaluator`) to `nvidia/nemotron-3.5-lightning-30b-a3b` (reasoning off) and S2 (`planner`, `cause_analyst`, `writer`) to `nvidia/nemotron-3-ultra-550b-a55b`.
- **Call reliability (`405 ok, 3 failed` = 99.3%):** With batched S1 relevance scoring (`S1_FILTER_BATCH_SIZE=16`), post-completion pacing (`MODEL_MIN_INTERVAL_S=1.8`), and Nightshift linear retry backoff (`LLM_RETRY_BACKOFF_S=8`), upstream NVIDIA 429/502 rate-limit errors were almost completely eliminated: **405 of 408 agent calls succeeded live** (19 of 22 questions had `0` failed calls; `q28`, `q32`, and `q38` had `1` failed call out of 20).
- **In-sample caveat:** Unlike the 22 Oct pre-guardrails run (`eval/RESULTS_dev_nvidia.md`, 14/22 vs 11/22), this re-run includes the PR #2 guardrails in `app/agents/core.py` (which were designed after inspecting the 22 Oct `dev` failure patterns on seasonality, promotion effect, and negative controls). Both scores are reported side by side for full transparency.
