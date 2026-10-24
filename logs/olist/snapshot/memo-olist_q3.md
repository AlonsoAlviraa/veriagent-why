# What drives 1-2 star reviews (orders purchased Jan 2017 - Aug 2018)?

_Run `olist_q3-snapshot-20261024-103408` · backend **snapshot** · $0 (no model calls)_

> Data: Brazilian E-Commerce Public Dataset by Olist (https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), CC BY-NC-SA 4.0. Non-commercial demo; derived memos and traces are shared under the same license.

**KPI** `olist.low_review_rate`: period 12.803

**Top supported cause:** H_late — Late deliveries get worse reviews

## Hypotheses

| hypothesis | evidence | treatment | control | ratio | outcome |
|---|---|---|---|---|---|
| H_freight | 1-2 star share, freight-heavy vs not | 13.563 | 12.391 | 1.0946 | refutes |
| H_late | 1-2 star share, late vs on time | 62.4 | 9.259 | 6.7391 | supports |
| H_interstate | 1-2 star share, interstate vs same state | 14.198 | 10.307 | 1.3774 | supports |
| H_multi_seller | 1-2 star share, multi-seller vs single | 47.248 | 12.341 | 3.8287 | supports |

## Why-diff (from hypothesis_update trace events)

- H_freight (prior #1): open -> **refuted** by q3_freight
- H_late (prior #2): open -> **supported** by q3_late
- H_interstate (prior #3): open -> **supported** by q3_interstate
- H_multi_seller (prior #4): open -> **supported** by q3_multi
- Prior first: H_freight; final top: H_late

## Sensitivity of the conclusion (deterministic, drop one source)

- without `ol_orders`: top cause None **(changes)**
- without `ol_items`: top cause H_late (same)
- without `ol_reviews`: top cause None **(changes)**
- without `ol_sellers`: top cause H_late (same)

## Claims and receipts

| claim | value | receipt | backend | db now |
|---|---|---|---|---|
| kpi_period (KPI in the period) | 12.803 | GREEN | snapshot | 12.803 |
| q3_freight_t (1-2 star share, freight-heavy vs not (treatment)) | 13.563 | GREEN | snapshot | 13.563 |
| q3_freight_c (1-2 star share, freight-heavy vs not (control)) | 12.391 | GREEN | snapshot | 12.391 |
| q3_late_t (1-2 star share, late vs on time (treatment)) | 62.4 | GREEN | snapshot | 62.4 |
| q3_late_c (1-2 star share, late vs on time (control)) | 9.259 | GREEN | snapshot | 9.259 |
| q3_interstate_t (1-2 star share, interstate vs same state (treatment)) | 14.198 | GREEN | snapshot | 14.198 |
| q3_interstate_c (1-2 star share, interstate vs same state (control)) | 10.307 | GREEN | snapshot | 10.307 |
| q3_multi_t (1-2 star share, multi-seller vs single (treatment)) | 47.248 | GREEN | snapshot | 47.248 |
| q3_multi_c (1-2 star share, multi-seller vs single (control)) | 12.341 | GREEN | snapshot | 12.341 |

System time (trace, investigation): 0.467 s; verify: 0.367 s

No accuracy metric: Olist has no ground truth for these questions.
