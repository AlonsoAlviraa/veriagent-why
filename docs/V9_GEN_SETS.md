# V9.1 generalization sets (built and frozen before any full model run)

Goal (Alonso, 25 Oct 2026): decide *with data* which confidence / abstention strategy generalizes and which is overfit to the
TAT-QA design slice. `oodsec` turned out too easy (V7 EM 99.18%, 3 errors), so it cannot separate strategies. These sets are
built to be harder (target V7 accuracy roughly 30-70%, at least ~100 errors per set) and are frozen here (ids, splits and
SHA-256 fingerprints) before any full run. Builder: `bench/v9_gen_build.py` (seed 20261025). Model under test:
Nemotron 3.5 Lightning (pre-training cutoff Sep 2025, post-training cutoff May 2026; see docs/V9_FINAL_SET.md).

## Candidates considered

| Candidate | Size | License | Shift vs TAT-QA | Leak risk (evidence) | Gold reliability | Pipeline effort | Decision |
|---|---|---|---|---|---|---|---|
| **SEC 10-Q multi-step (programmatic)** `gen_secq` | 400 (100 filings) | public-domain SEC data | quarterly filings, 4-column table (Q / prior Q / YTD / prior YTD), balance-sheet + cash-flow in text, 2-4 step ratios / differences, 2026 companies not in oodsec | **low**: every 10-Q was filed 1 Jul - 29 Sep 2026, after both cutoffs; questions are new strings | high: values from XBRL companyfacts, gold computed by code; 20-item spot-check against filing HTML, 896/896 source values found (`docs/v9/gen/secq_spotcheck.json`) | medium (built here) | **use** |
| **jfinqa** (HF `ajtgjmdjp/jfinqa`) `gen_jfinqa` | 927 → 400 numeric | Apache-2.0 | **Japanese** questions and statements (yen, 百万円, fiscal "2024年3月期"), program-of-thought gold | **low-moderate**: dataset created 7 Feb 2026, after the pre-training cutoff but before the post-training cutoff (May 2026) | medium: gold re-executed from the program and checked against the stated answer; 154/415 programs use unrounded operands while the table shows rounded values (relative effect < 0.1%, inside the semantic tolerance); one inspected table is internally inconsistent (operating income ≠ gross profit − SG&A), so values may not match the real filings — the questions remain answerable from the given context | low | **use** |
| **FinQA test** (github czyssrs/FinQA) `gen_finqa` | 1,147 → 400 | MIT | longer S&P 500 10-K pages, multi-step programs, many tables | **high**: public since 2021, before the Sep-2025 pre-training cutoff; very likely seen | medium: kept only items whose re-executed program agrees with the stated answer (179 disagreeing and 39 non-executable items dropped); gold scale often missing in FinQA | low | **use, leak declared** |
| MultiHiertt (dev) | 1,044 | MIT | multi-table hierarchical HTML | high (2022) | medium | high (multi-table HTML → TAT-QA format) | skipped (effort) |
| FinLongDocQA (2026) | — | non-standard | 129k-token documents | low | LLM-generated QA | high | skipped (license, gold) |
| FinNumReason | — | — | operands are given in the question | — | — | — | skipped (not retrieval/reading) |

## Frozen sets

| Set | Items | Cal / Test | Tables (bootstrap clusters) | Pilot (disjoint docs, excluded) | dataset sha256 | split sha256 |
|---|---|---|---|---|---|---|
| gen_secq | 400 | 100 / 300 | 100 | 16 | `201529949235760d3a4011d880addc8c7bf3fb782da5802f4ce2901996cf86fb` | `fdc803cfbc5a3196a146a964da316366f325414487595e2c9c27cb96384d21ab` |
| gen_jfinqa | 400 | 95 / 305 | 54 | 15 | `45f3cd1dcabafe1023dc9eafc2775a47d8c6a64c3d5857bf640ec6997418bcd0` | `f7001b34f05ef74c3232ade7ea5ac0542e115372a3ccabba74071bc346d38f31` |
| gen_finqa | 400 | 104 / 296 | 252 | 15 | `c0fff5baf9d45c74e13b966b8b326ac931239645bdd3c8b6819e5a0d1093eaf8` | `9493a6be0ccfbea571da8cd3839033f306fca6cdaa30552522d33d6f51bc0fa3` |

Cal/test split is by table (document), 25% cal. Ids are disjoint from test500, oodsec, the V9 design slice and all earlier
slices (different uid prefixes `gensecq-`, `genjfinqa-`, `genfinqa-`; SEC CIKs are disjoint from oodsec).
Files: `docs/v9/gen/tatqa_dataset_gen_*.json`, `split_gen_*.json`, `split_gen_*_pilot.json`.

## Notes
* `gen_secq` is a programmatic set: the question templates are ours (gross margin and its pp change, operating margin, effective
  tax rate, growth differences, YTD − quarter, current ratio and its change, liabilities/equity, free cash flow and FCF margin,
  OCF/net income, cash/revenue). At most 4 questions per filing, at least one from table, text and table+text where possible.
  An earlier provisional build (commit f09e68b) used the wrong prior date for equity; it was fixed and the set rebuilt before any
  run on it (only the fixed build is used).
* Pilots (15-16 items per set, disjoint documents) were run only to check the pipeline and the accuracy range; they are excluded
  from every reported number.
