# Eval results: dev split, provider `sample`

Measured by `eval/eval.py` on seeded synthetic data. Metric: exact match of `top_cause_label`.

| System | Correct |
|---|---|
| VeriAgent Why | 18/18 (Wilson 95% CI 0.82–1.00) |
| Plain-RAG baseline | 5/18 (Wilson 95% CI 0.12–0.51) |

Secondary metrics (agent): segment match 10/10, secondary cause detected 1/2, secondary false positives 0/16.

| qid | kind | expected | agent | baseline |
|---|---|---|---|---|
| q01 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q02 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q03 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q04 | breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | promotion_effect |
| q05 | negative_control | none | none | none |
| q06 | carrier_breach | carrier_sla_breach | carrier_sla_breach | none |
| q25 | seasonality | seasonality | seasonality | none |
| q26 | seasonality | seasonality | seasonality | none |
| q27 | promotion_effect | promotion_effect | promotion_effect | promotion_effect |
| q28 | promotion_effect | promotion_effect | promotion_effect | promotion_effect |
| q29 | noisy_breach | carrier_sla_breach | carrier_sla_breach | none |
| q30 | noisy_breach | carrier_sla_breach | carrier_sla_breach | none |
| q31 | multi_cause | carrier_sla_breach | carrier_sla_breach | none |
| q32 | multi_cause | carrier_sla_breach | carrier_sla_breach | none |
| q33 | noisy_breach_with_date_promo_trap | carrier_sla_breach | carrier_sla_breach | promotion_effect |
| q34 | noisy_negative_distractor | none | none | none |
| q35 | noisy_seasonality | seasonality | seasonality | none |
| q36 | noisy_promotion_effect | promotion_effect | promotion_effect | promotion_effect |
