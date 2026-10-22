# Eval results: dev split, provider `sample`

Measured by `eval/eval.py` on seeded synthetic data. Metric: exact match of `top_cause_label`.

| System | Correct |
|---|---|
| VeriAgent Why | 10/10 (Wilson 95% CI 0.72–1.00) |
| Plain-RAG baseline | 3/10 (Wilson 95% CI 0.11–0.60) |

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
