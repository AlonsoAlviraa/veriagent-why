# Why did the late-delivery rate jump in Feb-Mar 2018 compared with Jan 2018?

_Run `olist_q1-zetaris-20261024-103834` · backend **zetaris** · $0 (no model calls)_

> Data: Brazilian E-Commerce Public Dataset by Olist (https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), CC BY-NC-SA 4.0. Non-commercial demo; derived memos and traces are shared under the same license.

**KPI** `olist.late_rate`: period 16.631 vs baseline 5.701

**Top supported cause:** H_transit — Carrier transit time (handed to carrier -> delivered) got longer

## Hypotheses

| hypothesis | evidence | treatment | control | ratio | outcome |
|---|---|---|---|---|---|
| H_transit | avg transit days | 13.17 | 10.483 | 1.2563 | supports |
| H_volume | delivered orders per day | 229.814 | 228.032 | 1.0078 | refutes |
| H_handling | avg seller handling days | 3.444 | 3.597 | 0.9573 | refutes |
| H_rj_only | late rate outside RJ (if it also rose, the rise is NOT RJ-only) | 14.032 | 4.695 | 2.9885 | refutes |

## Why-diff (from hypothesis_update trace events)

- H_transit (prior #1): open -> **supported** by q1_transit
- H_volume (prior #2): open -> **refuted** by q1_volume
- H_handling (prior #3): open -> **refuted** by q1_handling
- H_rj_only (prior #4): open -> **refuted** by q1_rest
- Prior first: H_transit; final top: H_transit

## Sensitivity of the conclusion (deterministic, drop one source)

- without `ol_orders`: top cause None **(changes)**
- without `ol_items`: top cause H_transit (same)
- without `ol_reviews`: top cause H_transit (same)
- without `ol_sellers`: top cause H_transit (same)

## Claims and receipts

| claim | value | receipt | backend | db now |
|---|---|---|---|---|
| kpi_period (KPI in the period) | 16.631 | GREEN | zetaris | 16.631 |
| kpi_baseline (KPI in the baseline) | 5.701 | GREEN | zetaris | 5.701 |
| q1_transit_t (avg transit days (treatment)) | 13.17 | GREEN | zetaris | 13.17 |
| q1_transit_c (avg transit days (control)) | 10.483 | GREEN | zetaris | 10.483 |
| q1_volume_t (delivered orders per day (treatment)) | 229.814 | GREEN | zetaris | 229.814 |
| q1_volume_c (delivered orders per day (control)) | 228.032 | GREEN | zetaris | 228.032 |
| q1_handling_t (avg seller handling days (treatment)) | 3.444 | GREEN | zetaris | 3.444 |
| q1_handling_c (avg seller handling days (control)) | 3.597 | GREEN | zetaris | 3.597 |
| q1_rest_t (late rate outside RJ (if it also rose, the rise is NOT RJ-only) (treatment)) | 14.032 | GREEN | zetaris | 14.032 |
| q1_rest_c (late rate outside RJ (if it also rose, the rise is NOT RJ-only) (control)) | 4.695 | GREEN | zetaris | 4.695 |

System time (trace, investigation): 16.432 s; verify: 9.182 s

No accuracy metric: Olist has no ground truth for these questions.
