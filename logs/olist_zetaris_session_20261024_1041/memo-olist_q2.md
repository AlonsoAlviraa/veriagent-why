# Why did the late-delivery rate spike in November 2017 (Black Friday month) compared with October 2017?

_Run `olist_q2-zetaris-20261024-103834` · backend **zetaris** · $0 (no model calls)_

> Data: Brazilian E-Commerce Public Dataset by Olist (https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), CC BY-NC-SA 4.0. Non-commercial demo; derived memos and traces are shared under the same license.

**KPI** `olist.late_rate`: period 12.404 vs baseline 4.176

**Top supported cause:** H_volume — Black Friday order volume surge

## Hypotheses

| hypothesis | evidence | treatment | control | ratio | outcome |
|---|---|---|---|---|---|
| H_volume | delivered orders per day | 242.933 | 144.452 | 1.6818 | supports |
| H_handling | avg seller handling days | 4.066 | 3.45 | 1.1788 | inconclusive |
| H_transit | avg transit days | 11.095 | 8.407 | 1.3197 | supports |

## Why-diff (from hypothesis_update trace events)

- H_volume (prior #1): open -> **supported** by q2_volume
- H_handling (prior #2): open -> **inconclusive** by q2_handling
- H_transit (prior #3): open -> **supported** by q2_transit
- Prior first: H_volume; final top: H_volume

## Sensitivity of the conclusion (deterministic, drop one source)

- without `ol_orders`: top cause None **(changes)**
- without `ol_items`: top cause H_volume (same)
- without `ol_reviews`: top cause H_volume (same)
- without `ol_sellers`: top cause H_volume (same)

## Claims and receipts

| claim | value | receipt | backend | db now |
|---|---|---|---|---|
| kpi_period (KPI in the period) | 12.404 | GREEN | zetaris | 12.404 |
| kpi_baseline (KPI in the baseline) | 4.176 | GREEN | zetaris | 4.176 |
| q2_volume_t (delivered orders per day (treatment)) | 242.933 | GREEN | zetaris | 242.933 |
| q2_volume_c (delivered orders per day (control)) | 144.452 | GREEN | zetaris | 144.452 |
| q2_handling_t (avg seller handling days (treatment)) | 4.066 | GREEN | zetaris | 4.066 |
| q2_handling_c (avg seller handling days (control)) | 3.45 | GREEN | zetaris | 3.45 |
| q2_transit_t (avg transit days (treatment)) | 11.095 | GREEN | zetaris | 11.095 |
| q2_transit_c (avg transit days (control)) | 8.407 | GREEN | zetaris | 8.407 |

System time (trace, investigation): 8.249 s; verify: 8.456 s

No accuracy metric: Olist has no ground truth for these questions.
