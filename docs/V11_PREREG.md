# V11 pre-registration — fresh benchmark (TableBench)

Committed **before any model call** on this set. One run, no tuning afterwards. Whatever the result, it is reported.

## 1. Question
Does the frozen final system (V7 answers + V9_full confidence) still beat plain RAG, and does its abstention layer still help, on data it has never seen, from a different domain?

## 2. Frozen system and config hash
- Code: `main` at `9e0af6b8682c59ea0a2423f216961501c3b9429c` (tree `3dbf6459...`), plus only the new files `bench/v11_build.py` and `bench/v11_analysis.py`. No file under `app/` changes.
- V9_full: `app/v9_full_model.json`, sha256 `566c4c09...0de6`. CRC λ = 0.683 (alpha 0.10), applied as-is. It is **never refit** on V11.
- Run environment: same as V10 (`docs/v11/config_v11.json`). Every LLM step uses Nebius `nvidia/Nemotron-3_5-Lightning`, with `V9=1`, `NEBIUS_STRICT=1`, `LLM_CACHE=0`, `--max-calls-item 40 --no-judge`, and `TATQA_SPLIT=v11_tablebench`.
- **config_sha256 = `52d302ebf6cc990c135a133e154e0cd89c50fb400ed594c4f44b53fa91529173`** (sha256 of the canonical JSON in `docs/v11/config_v11.json`; no secrets in it).
- Why Nebius and not the NVIDIA free tier: the V9 features use the answer's token log-probabilities and were fitted on Nebius Lightning outputs. Changing the provider would change the system under test.

## 3. Benchmark and why
**TableBench** (Wu et al., AAAI 2025): HF `Multilingual-Multimodal-NLP/TableBench`, file `TableBench.jsonl`, revision `a23c244f9ccae1ea238d614fe7620984707e411a`, **Apache-2.0**.
- **Never seen.** It is not TAT-QA, test500, oodsec, the V9.1 sets (SEC/JFinQA/FinQA) or V10 (MultiHiertt/DocFinQA). It also shares no source with them: its tables are general-domain (sports, elections, geography, science), not financial reports.
- **Professional and harder.** It is a human-annotated, peer-reviewed benchmark built to stress LLMs on table QA, across 18 reasoning subtypes (multi-hop, aggregation, time-based, statistics). Every item has a gold answer.
- **Why not the others.** FinanceBench is CC BY-NC 4.0 (non-commercial) and needs full PDFs. ConvFinQA reuses the FinQA filings already used in V9.1. TableBench is the cleanest permissive, unseen, different-domain choice.
- **Honest caveat.** TableBench is table-only (no text paragraphs), so the "text" half of table-text QA is not tested here.

## 4. Sample and fingerprint (`python -m bench.v11_build /workspace/v11/TableBench.jsonl`)
- Source sha256: `ebcc6fcea565c9c0a51ecf1c72be58b3b7db7e9466a6a9581d0dc882cc72279e` (886 items).
- Kept: every item whose gold is a single number, excluding TrendForecasting (forecasts are not grounded in the table). Dropped: 474 non-numeric, 50 TrendForecasting, 1 exact duplicate id.
- **n = 361.** All eligible items are used, with no sub-sampling and no seed choice.
- Fingerprint:
  - ids sha256 `a5d6d3d76b58cbdb380e2efe79d556b94a05f1ea865964cd0e68a8a8fb18c22f`
  - dataset sha256 `b8ad9b9a77d18fdeb410cf7f628fe2915f477d81e47926105ccf8cf93f4c5737`
  - split file sha256 `6adf7aaef2d991b94a6e76b0a298851c7d96f1407e14281da6aa4422b09fa7e3`
- Files: `docs/v11/tatqa_dataset_v11_tablebench.json`, `docs/v11/split_v11_tablebench.json`.

## 5. Systems compared (one run produces all of them)
| Arm | What |
|---|---|
| **V7+V9** (final system) | V7 agent answer; answer if V9_full p ≥ 0.683, else abstain (`app/v9conf.row_decision`) |
| **V7 without V9** | the same V7 answers, always answered |
| **Plain RAG** (reference baseline) | `rag` system, always answered. It is reported as the reference even if it wins |
| **Trivial rule** | median of all numeric table cells, with zero model calls |

## 6. Metrics (`bench/v11_analysis.py`, frozen in this commit)
- **Semantic correctness** (primary; `bench.v9_final.score`, the same scorer as V9/V10) and TAT-QA **EM** (secondary).
- Paired bootstrap 95% CIs over items (B=2000, seed 2026) for V7−RAG, V7−trivial and RAG−trivial.
- For V9:
  - coverage and abstention rate
  - selective accuracy, with a CI
  - realized risk (wrong answers given / n) vs the alpha 0.10 target
  - selective accuracy − V7 accuracy, with a paired CI
  - AUROC (with CI) of V9_full vs the cheap signals (V7 `confidence_det`, traceability gate), plus the paired AUROC difference
- **Net score:** +1 correct, −1 wrong, 0 abstain. Compared as V7+V9 vs RAG and vs V7, with paired CIs.
- Per-subtype accuracy, plus the full list of failures.
- Errored rows count as wrong. For V7+V9 they count as abstentions. They are never re-run.

## 7. Acceptance rules
- **A1:** the CI lower bound of V7 − RAG semantic accuracy is > 0.
- **A2:** the CI lower bound of V9_full AUROC is > 0.5 **and** the CI lower bound of selective accuracy − V7 accuracy is > 0.
- **A3** (reported, not in the verdict): realized risk ≤ 0.10.
- **A4:** the CI lower bound of net score V7+V9 − RAG is > 0.
- **Verdict:**
  - **WORKS** if A1, A2 and A4 all hold.
  - **PARTIAL** if 1–2 of them hold.
  - **DOES_NOT_WORK** if none hold.
  - If the upper CI bound of V7 − RAG is < 0, it says **RAG wins**.

## 8. Budget and stop rule
- Prior per-item cost (V10 rows): about $0.0047 for agent_v9 and $0.0002 for RAG, so the estimate is about $1.8 for 361 items.
- Cap: $5 on Nebius. Ledger before the run: $13.65. The run uses `NEBIUS_BUDGET_USD=18.65` as a hard guard; this is a spend guard only, not a model setting.
- The ledger is checked after each batch (shard). If the guard trips, the run stops and the partial result is reported as is.

## 9. Deliverables
`docs/V11_RESULTS.md`, `docs/v11/results_v11.json`, and the raw rows and traces under `docs/v11/runs/` with sha256 in `docs/v11/MANIFEST.sha256`.
