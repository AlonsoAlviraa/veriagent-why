# Eval results: test split, provider `sample`

Measured by `eval/eval.py` on seeded synthetic data. Metric: exact match of `top_cause_label`.

| System | Correct |
|---|---|
| VeriAgent Why | 14/18 (Wilson 95% CI 0.55–0.91) |
| Plain-RAG baseline | 6/18 (Wilson 95% CI 0.16–0.56) |

| qid | kind | expected | agent | baseline |
|---|---|---|---|---|
| q07 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q08 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q09 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q10 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q11 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q12 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q13 | breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | promotion_effect |
| q14 | breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | promotion_effect |
| q15 | breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | promotion_effect |
| q16 | seasonality | seasonality | none | none |
| q17 | seasonality | seasonality | none | none |
| q18 | seasonality | seasonality | none | none |
| q19 | promotion_effect | promotion_effect | carrier_sla_breach | promotion_effect |
| q20 | promotion_effect | promotion_effect | promotion_effect | promotion_effect |
| q21 | promotion_effect | promotion_effect | promotion_effect | promotion_effect |
| q22 | negative_control | none | none | none |
| q23 | negative_control | none | none | none |
| q24 | negative_control | none | none | none |

## How to read this (written after the single test run on 22 Oct 2026)
- Provider `sample`: **no language model on either side**. The agent ran its deterministic path; the baseline used its fixed reader rule (see `eval/baseline_rag.py`). This is not the Nemotron comparison; that run is pending an NVIDIA/Nightshift endpoint and will be reported separately.
- Same data, questions and retrieval-token budget (the baseline gets the agent's own S2 context size per question).
- Misses: all 3 seasonality questions (the agent has no seasonality hypothesis yet; it answers `none`) and 1 of 3 promotion_effect questions (q19, labelled carrier_sla_breach). Both trap types are test-only by design and were never seen during dev tuning.
- 18 questions is a small sample; the intervals overlap only narrowly and no significance is claimed. Synthetic data with planted causes.
