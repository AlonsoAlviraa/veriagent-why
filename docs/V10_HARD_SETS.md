# V10 hard sets: harder held-out benchmarks

**Goal.** V9.1 sets were too easy for a strong abstention story: V7 scored 70–75% semantic. V10 adds two public, licensed financial QA sets where published strong-model accuracy is near or below 40–50%. On these sets most answers are wrong, so knowing when to abstain matters most.

Builder: `bench/v10_hard_build.py`, which reuses the V9.1 protocol from `bench/v9_gen_build.py`:
- seed 20261025
- at most 400 questions per set
- calibration/test split of 25/75, made **by document**
- a disjoint 15-item pilot pool
- sha256 fingerprints

**No model was called while building or choosing these sets.** Selection used only metadata, gold re-execution and published numbers.

## Candidates screened (ranked)
| Rank | Dataset (HF) | License | Published difficulty | Decision |
|---|---|---|---|---|
| 1 | `yilunzhao/MultiHiertt` dev | MIT | Fine-tuned MT2Net 36.2 EM. GPT-4 direct 41.4, CoT 55.1, PoT 67.2. Human 83.1. Questions over ≥2 tables drop to about 21–24 for fine-tuned models | **Chosen** (`hard_mhiertt`) |
| 2 | `kensho/DocFinQA` test | MIT | Best retrieval system on test: GPT-3.5 42.6, Mistral-7B 25.0. On 100k+ token filings: GPT-4 with retrieval 47.5, without retrieval 20–23, non-expert humans 41.0 (Reddy et al., ACL 2024, Tables 3–4) | **Chosen** (`hard_docfinqa`) |
| 3 | `yale-nlp/DocMath-Eval` (complong) | MIT | Hard long-document multi-table subset | **Gated** (HTTP 401 without an HF login that has accepted the terms). Needs Alonso's HF account. Optional third set |
| 4 | TableBench | Apache-2.0 | GPT-4o numerical reasoning 68.5 | Not hard enough for the <40% target; not finance. Rejected |
| 5 | FinLongDocQA (arXiv 2604.03664) | non-standard | Hard split 9–25 EM | Rejected: license, and the QA is LLM-generated (as in V9) |
| — | FinanceBench, FinDER, RealHiTBench | CC-BY-NC | — | Rejected: license |
| — | FinSearchComp, FAMMA | — | — | Rejected: needs web search or images; FAMMA live answers are missing |

Leakage note: both datasets date from 2022 and 2024, so the questions may be in model pretraining. The low published scores suggest memorization does not solve them. This is a stress test of difficulty and abstention, **not** a contamination-free test. The contamination-free sets stay V9.1 `gen_secq` (filed in 2026) and `gen_jfinqa`.

## hard_mhiertt (MultiHiertt dev, 1044 questions → 400 + 15 pilot)
Filter (counts in `docs/v10/hard/split_hard_mhiertt.json`):
- keep arithmetic questions whose FinQA-DSL program re-executes to the stated answer
- span questions dropped: 202
- program disagrees with the answer: 7
- easy questions dropped (<2 program steps AND evidence in a single table): 196
- eligible: 639

Format: each report's 3–7 HTML tables are flattened into one grid with a `[Table k]` separator row. All report paragraphs become TAT-QA paragraphs. The cal/test split is grouped by report: 218 reports, 96 cal and 304 test questions.

Median context is about 14k characters, roughly 3–4× a FinQA item.

Sampled rows (gold is the dataset program re-executed):
- "what is the growth rate in operating profit for space systems in 2011?" → 0.032 (stated 0.03204; 2 steps)
- "In the year with largest amount of government, what's the increasing rate of education?" → −0.0093 (2 steps)

## hard_docfinqa (DocFinQA test, 922 questions → 400 + 15 pilot)
Context is a full 10-K: about 550k characters on average, too long for the full-context agent. The builder therefore freezes **one retrieval**:
- split the filing into chunks of about 2000 characters
- retrieve the top 8 by BM25 (`app.bm25`) against the question
- store the result, so every arm sees exactly the same evidence (about 14k characters)

Gold comes from a **safe AST evaluation** (no `exec`) of the dataset's Python program, kept only when it agrees with the stated answer. Dropped: 154 empty programs, 22 unparsable, 3 disagreeing.

Each question gets `operands_in_context`: whether every literal in the program occurs in the retrieved text. The rate is 0.72, so for **about 28% of items the needed numbers are probably missing**, and abstention is the right behaviour there. This is a pre-declared stratum.

The split is grouped by filing: 187 filings, 102 cal and 298 test questions.

Sampled rows:
- "in 2006, what percent of unrealized loss did foreign currency translation offset?" → 86.7841% (stated 86.78%)
- "what portion of the 1999 accrual balance related to restructurings is comprised of canceled contracts?" → 50%

## Fingerprints
| Set | dataset sha256 | split sha256 |
|---|---|---|
| hard_mhiertt | `12a6320c1a40c5e3524a75bff558da5bee0c6af0b6d0a3203f187e3f588610fd` | `ad6871ee61e5eca5af8e2296f2a7721325bbda09d8cc22752254a269b147e888` |
| hard_docfinqa | `2c6e010d83a5f4dc14cbeed31207ed7aeec89e3ee66ddc65ecc44a43587e4a58` | `ec7ffeca51e5a6422ca54df0b5db794462760485bd57e07b62f85068877dd474` |

Files: `docs/v10/hard/` holds the datasets, `split_*.json` and `split_*_pilot.json`. To rebuild:

```
python -m bench.v10_hard_build <work>
```

`<work>` must contain `mh_dev.json`, downloaded from HF `yilunzhao/MultiHiertt` at `resolve/main`, and `docfinqa_test.parquet`, from the HF parquet conversion of `kensho/DocFinQA`. Run it with pandas and pyarrow installed. Load a set with `TATQA_SPLIT=hard_mhiertt` or `TATQA_SPLIT=hard_docfinqa`.
