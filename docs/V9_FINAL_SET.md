# V9 final test set: `oodsec` (out-of-distribution, post-cutoff SEC filings)

Built and committed **before any model run on it** (Sat 24 Oct 2026, ~23:00 Madrid). Alonso's requirement (24 Oct): no leakage, an
out-of-distribution set the model is not used to. TAT-QA train hold-out (`docs/v9/holdout.json`) is therefore **not** used as the
final test (it stays unopened).

## Model cutoff (documented)
NVIDIA model card for Nemotron 3.5 Lightning (build.nvidia.com / Hugging Face, read 24 Oct 2026): pre-training data cutoff
**September 2025**, post-training data cutoff **May 2026**; Common Crawl snapshots up to CC-MAIN-2025-13.

## Candidates considered
Sizes/licences of public benchmarks are as stated in their papers/repos from memory and were **not re-verified tonight**; the
decisive criterion (public before the model's cutoff) does not depend on them.

| candidate | size | licence | shift vs TAT-QA | leak risk | gold reliability | effort |
|---|---|---|---|---|---|---|
| TAT-QA train hold-out (pre-registered) | 400 | CC BY 4.0 | none | **high**: public since 2021, before Sep-2025 pre-training cutoff | human | 0 |
| TAT-DQA | ~16k | CC BY 4.0 | doc images/PDF (needs OCR) | high: public since 2022 | human | high (OCR path) |
| FinQA / ConvFinQA | ~8k / ~3.9k conv. | MIT | S&P 500 10-Ks 1999-2019, programs | high: public since 2021-22 | human | medium (format adapter) |
| MultiHiertt | ~10k | MIT | multi hierarchical tables | high: public since 2022 | human | medium |
| FinanceBench (open 150) | 150 | CC BY-NC | open-book PDFs | high: public 2023; too small; non-commercial | human | high |
| Newer 2025 HF finance QA sets | varies | varies | varies | medium-high: anything public before Sep 2025 may be in pre-training | varies | medium |
| **`oodsec` (built here)** | **368 q / 92 tables** | US-government public data (SEC EDGAR) | new companies, FY2026 vs FY2025, XBRL line items, templated text | **low** (see below) | **programmatic** + hand spot-check | done |

**Chosen: `oodsec`.** It is the only option whose leak resistance is structural rather than hoped-for. No fallback was needed;
if `oodsec` had failed the checks below, the plan was to STOP and report.

## Construction (`bench/v9_ood_build.py`, deterministic, seed 20261024)
* Source list: every 10-K in EDGAR full-index **filed 2026-06-01 … 2026-10-24** (552 filings, 548 CIKs:
  `docs/v9/ood/edgar_10k_filed_2026-06-01_to_2026-10-24.txt`). XBRL `companyfacts` per CIK; **only facts with that filing's
  accession number**, USD, ~1-year durations; current and prior fiscal year from the same filing.
* Table: up to 8 standard line items (Revenue, Cost of revenue, Gross profit, R&D, SG&A, Operating income, Income tax expense,
  Net income), "(In millions)", integer millions; rows with |value| < 10 dropped; revenue ≥ $100M; ≥ 3 rows; header `Fiscal 2026 | Fiscal 2025`.
* Text: one templated header sentence (entity, filing date, period ends) plus one templated sentence per cash-flow/other item
  (operating cash flow, capex, D&A, interest expense, share-based compensation). **The text is templated, not filing prose** (declared).
* Questions (templated, 4 per table, ≥1 from each of table / text / table-text where available): value lookup (span), change,
  percentage change, average, and text-item as % of revenue. **Gold = Python arithmetic on the displayed numbers**, rounded to 2 dp,
  TAT-QA conventions (change = new − old; % change over |old|; scale `million`/`percent`). No LLM involved anywhere in the gold.
* Mix: arithmetic/table-text/percent 98, arithmetic/table/million 65, span/text 61, arithmetic/text 54, span/table 46,
  arithmetic/table/percent 44. Filing months: Jun 32, Jul 13, Aug 33, Sep 14 tables.
* Format: TAT-QA JSON (`table`, `paragraphs`, `questions`), so the harness runs unchanged with `TATQA_SPLIT=oodsec`.
  The only adaptation: questions whose gold would be exactly 0 are removed, because the official TAT-QA scorer cannot score a
  gold of 0 (found by the oracle self-check: 3 such items).

## Checks done before the run
* **Oracle self-check:** feeding each gold back through the official TAT-QA scorer gives EM = 1 on 368/368.
* **Hand spot-check against the filings:** 10 random tables, 2 values each, searched in the filing's primary 10-K HTML
  (as thousands, millions or units): **20/20 found** (e.g. Cisco revenue 63,325; Darden revenue 13,210.9; Amcor revenue 23,506).
* **No overlap:** all ids are new (`oodsec-<sha16>`); none appears in any earlier run file or repo file; tables are new companies/years.
* **Fingerprints:** dataset `docs/v9/ood/tatqa_dataset_oodsec.json` sha256 `332cd9925285877a17051970e5f3d51aee79449a5d71b86f42d085046e6ee0cf`;
  id list `docs/v9/final_oodsec.json` sha256 `d41c87dc9f3ae1bce2cf535a75e6f74d8a3819e0f189ec63567c47758d9de8a1` (368 ids).

## Leak-risk assessment
* Every FY2026 figure first became public in a filing dated **after** the model's post-training cutoff (May 2026) and long after
  its pre-training cutoff (Sep 2025). The questions and contexts are new strings created tonight.
* Residual risks (declared): prior-year (FY2025) figures of fiscal years ending before ~Aug 2025 may be in pre-training; the model
  could know a company's approximate scale. The answer still requires the FY2026 figure, which is in the context only.
* Distribution shift vs TAT-QA: different companies and years, standardized XBRL labels, short templated paragraphs, narrower
  question templates (no counting/"respective"/multi-span), all values in millions. **It is likely easier in text understanding
  and harder in being unfamiliar**; absolute EM is not comparable with TAT-QA numbers.

## Limits
368 questions from 92 tables (4 per table): items are clustered; the analysis reports a table-cluster bootstrap as a sensitivity
check next to the pre-registered item bootstrap. Templated questions are less varied than TAT-QA's human-written ones.
