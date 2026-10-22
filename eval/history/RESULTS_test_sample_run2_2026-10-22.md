# Eval results: test split, provider `sample`

Measured by `eval/eval.py` on seeded synthetic data. Metric: exact match of `top_cause_label`.

| System | Correct |
|---|---|
| VeriAgent Why | 18/18 (Wilson 95% CI 0.82–1.00) |
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
| q16 | seasonality | seasonality | seasonality | none |
| q17 | seasonality | seasonality | seasonality | none |
| q18 | seasonality | seasonality | seasonality | none |
| q19 | promotion_effect | promotion_effect | promotion_effect | promotion_effect |
| q20 | promotion_effect | promotion_effect | promotion_effect | promotion_effect |
| q21 | promotion_effect | promotion_effect | promotion_effect | promotion_effect |
| q22 | negative_control | none | none | none |
| q23 | negative_control | none | none | none |
| q24 | negative_control | none | none | none |
