# Public benchmarks (InsightBench, TAT-QA)

Status: **harness plus pilot only**. None of the numbers below are final results. Every number marked *pilot* comes from a tiny sample (n=3 or n=15) and should not be cited as a benchmark score.

## Datasets and licences

The data is downloaded on demand and is never committed (`data/bench/` and `bench/results/` are gitignored). No login is needed.

```
pip install -r bench/requirements-bench.txt
python -m bench.download all          # writes data/bench/<bench>/MANIFEST.json with sha256 per file
```

| Benchmark | Source (pinned) | Data licence | Code licence |
|---|---|---|---|
| InsightBench (Sahu et al., 2024, arXiv:2407.06423) | github.com/ServiceNow/insight-bench @ `33c27c1`; file list from the HF dataset `ServiceNow/insight_bench` | The HF dataset card says **CC-BY-4.0**, but the paper states **CC BY-NC 4.0**. We declare both and treat the data as **non-commercial** to be safe. | MIT |
| TAT-QA (Zhu et al., ACL 2021) | github.com/NExTplusplus/TAT-QA @ `870accc` (dev set plus the official `tatqa_metric.py`) | CC BY 4.0 | MIT |

Please cite the original papers when you report results.

## Systems (all on the same model)

- **agent**: the VeriAgent Why pipeline. It runs Planner → SQL evidence (DuckDB, read-only guard) → Evidence Evaluator loop → Writer → a deterministic **claim gate**. The gate checks every number against the cited query results, allows up to 2 rewrites, and drops any insight that is still unsupported. On TAT-QA the model must provide evidence quotes and an expression; the gate checks that the quotes appear in the context, that the expression's numbers appear in the context, and that `eval(expr) == answer`.
- **rag**: plain RAG. It retrieves BM25 top rows/paragraphs (InsightBench budget about 3000 tokens; TAT-QA top-3 paragraphs plus the table) and answers in one call.
- **react**: ReAct. On InsightBench it writes text-to-SQL, with up to 6 SQL steps and then a final call. On TAT-QA it uses a calculator tool with up to 4 steps.

`BENCH_SINGLE_MODEL=1` (the default) sends every step of every system to the same model.

## Scoring

- **InsightBench**:
  - Official ROUGE-1 (`rouge_score`, no stemmer, as in HF `evaluate`) for the summary and for insights. Insights use one-to-many best match per ground-truth insight.
  - The verbatim G-Eval "basic" prompt as LLM judge, run with **Nemotron** on the same model.
  - **Deviation:** the paper uses LLaMA-3-70B with logprob-weighted scores. We parse the integer `<rating>` (0–10) and divide by 10, so our judge scores are *not* directly comparable to the paper's LLaMA-3-Eval.
  - The insight-level judge is opt-in (`--judge-insights`, one call per pair).
  - Our declared thresholds for k/n are judge ≥ 0.6 and insight ROUGE-1 ≥ 0.25. The k/n figures come with Wilson 95% intervals.
- **TAT-QA**:
  - Official `TaTQAEmAndF1` (EM/F1, scale-aware).
  - An **unsupported-number rate**: the share of numeric answers that cannot be traced to a context number or to one arithmetic step over context numbers (binary op, % change, mean). The same check is applied to every system.

Reference numbers from InsightBench paper Table 1 (5 seeds; verified from arXiv HTML):

| Agent | Insight ROUGE-1 | Insight LLaMA-3-Eval | Summary ROUGE-1 | Summary LLaMA-3-Eval |
|---|---|---|---|---|
| PA (gpt-4o) | 0.35 | 0.54 | 0.35 | 0.40 |
| AgentPoirot (gpt-4o) | 0.32 | 0.60 | 0.37 | 0.44 |
| AgentPoirot (gpt-4-turbo) | 0.30 | 0.56 | 0.35 | 0.35 |
| AgentPoirot (gpt-3.5) | 0.34 | 0.50 | 0.27 | 0.31 |
| AgentPoirot (llama-3-70b) | 0.33 | 0.52 | 0.36 | 0.33 |

## Runner

```
python -m bench.run --bench insightbench|tatqa --systems agent,rag,react \
  [--limit N] [--ids ...] [--max-calls 200] [--max-calls-item 40] [--rpm 30] \
  [--no-judge] [--judge-insights] [--dry-run] [--offline --fixtures] [--out file.jsonl]
python -m bench.report bench/results/<file>.jsonl [--md out.md]
```

- Results are written as resumable JSONL: (system, id) pairs that finished without an error are skipped on the next run.
- Two hard call caps apply, one per run and one per item.
- Pacing defaults to 30 rpm for the NVIDIA free tier (`MODEL_MIN_INTERVAL_S`). The tier allows about 40 rpm but shares that limit with other work, so we stay at or below 30.
- `--offline --fixtures` runs on hand-made fixtures (labelled as such) with a scripted fake model. CI runs it via `tests/test_bench_offline.py`, which needs no network.

## Providers and the hard spend guard

- `LLM_PROVIDER=nvidia` (the default for live runs) uses the NVIDIA free tier with `NVIDIA_API_KEY`.
- `LLM_PROVIDER=nebius` uses Nebius Token Factory (OpenAI-compatible, `NEBIUS_API_KEY`, model `NEBIUS_MODEL`, default `nvidia/Nemotron-3_5-Lightning`), implemented in `bench/nebius.py`. Nebius charges the card on file once the promo credit runs out and has no platform cap, so `bench/nebius.py` enforces a **hard software budget**:
  - A persistent cumulative ledger, `NEBIUS_LEDGER`, defaults to `~/.veriagent/nebius_spend.json`. It lives outside the repo, is shared by all processes, and is protected by `flock`.
  - Before each call, the guard reserves the worst-case cost: a conservative prompt estimate plus `max_tokens`, priced at the published per-1M prices. The call is refused if spent + in-flight reservations + worst case would exceed `NEBIUS_BUDGET_USD` (default 20). Models without a published price are refused outright.
  - When a call is refused, the process falls back to the NVIDIA free tier.
  - Actual cost comes from the returned `usage`. If the request was sent but returned no usage (timeout or 5xx), the worst case is booked.
  - Per-item `nebius_usd` appears in the JSONL and in `bench.report`. `bench.run` prints the ledger status at the end of each run.
- Prices ($/1M tokens, in/out): Lightning 0.06/0.24, Nano-30B 0.06/0.24, Super-120B 0.30/0.90, Ultra-550B 1.00/3.00.
- Policy: use Nebius Lightning for pilots and development, and reserve Super (Nebius or NVIDIA) for the final eval.
- On Nebius, thinking is disabled (`enable_thinking=false`). JSON mode (`response_format=json_object`) is enabled when the prompt asks for JSON, because Lightning otherwise often returns a bare answer.

## v2 harness changes (post-audit, 2026-10-23)

These come from the audit of the v1 dev run. All of them apply to **agent, rag and react alike**, unless the text says otherwise.

- **TAT-QA scale/format post-step** (`bench/tat_post.py`). It is deterministic and uses only the question, the context and the system's own answer. It **never reads the gold answer or the gold scale**, and a test checks that. The rules:
  - **Format:** strip `$`, commas and `%`. Parentheses become a negative sign. Numbers are rounded to 2 decimals.
  - **Scale:**
    - `percent` if the question asks for a percentage, a proportion or a percentage change;
    - `""` for text answers, counts and years;
    - otherwise the unit the context gives for the figures the answer uses: a table header or introducing paragraph that says "in thousands", "in millions", "USD '000" and so on, or a paragraph number written as "$3.4 million";
    - `""` if the context gives no unit.

  We score both the raw answer (`EM_raw_no_post`) and the post-processed one, so the step's contribution is visible.
- **TAT-QA convention prompt.** It states the scale rules, 2-decimal rounding, the shortest exact span, and lists for "respective" questions. It also asks for a `confidence` in [0, 1].
- **Dict answers are flattened** (the RAG `sorted()` TypeError) and so are dict evidence ids (the InsightBench flag-14 TypeError).
- **InsightBench output and context:**
  - up to 10 plain-prose insights plus a ground-truth-style summary (v1: at most 6, under 40 words);
  - results of up to 100 rows and 4,000 characters (v1: 40 rows, 1,500 characters);
  - a RAG context budget of 6,000 tokens (v1: 3,000).
- **Agent: SQL retry.** On a failed query the agent makes one fix call with the DuckDB error message. The harness logs the SQL error rate on the first try and after the retry, for agent and react.
- **Agent claim gate.** A number now passes if it appears in the cited results or can be **recomputed** from two of them:
  - the operations are a+b, |a−b|, a/b, |a−b|/b, ×100 for percentages, and the mean of two;
  - the match is precision-aware: the value must agree to half a unit of the claim's last digit;
  - every dropped claim is logged in `output.dropped_claims`, with its unsupported numbers and the reason.

  **Limitation:** recomputation from 25 values builds a dense pool. In a synthetic test on random numbers, about 22% of random integers and about 61% of random one-decimal percentages "match" by chance. A derived pass is therefore weaker evidence than a direct match.
- **flag-36** has no ground-truth insights in the dataset. It is reported under `excluded` and left out of InsightBench means and counts. It is not dropped silently.
- **Errors:** item errors count as 0 in means and as failures in counts.
- **Per-request timeout:** 90 s (`MODEL_TIMEOUT_S`), with up to 3 attempts with backoff on timeouts, 429 and 5xx. `NEBIUS_STRICT=1` still stops the run instead of overspending or falling back.

### Reported metrics (v2)

| Metric | Shown as |
|---|---|
| TAT-QA EM | Wilson 95% CI |
| TAT-QA F1 mean | bootstrap 95% CI (2,000 resamples, seed 2026) |
| TAT-QA per-answer-type breakdown | EM/F1 mean by `answer_type`, the same pivot as the official `get_detail_metric` |
| InsightBench insight ROUGE-1, summary ROUGE-1, summary judge | means with bootstrap CIs |

The ROUGE ≥ 0.25 and judge ≥ 0.6 counts are our own thresholds and are **secondary** only.

### Explainability metrics (Track 02), `bench/explain.py`

They are deterministic except for faithfulness. A claim is one final insight in InsightBench, or the answer in TAT-QA. Citations point into the system's own evidence store: query results `q1..` for the agent, retrieved row ids for RAG, observation numbers for ReAct. In TAT-QA they are verbatim evidence quotes.

| Metric | Definition |
|---|---|
| **citation precision** | Valid citations divided by all citations. A citation is valid if it exists (the id is in the store, or the quote appears verbatim in the context) **and** supports the claim's number, directly or by recomputation. For claims without numbers, existence is enough. In TAT-QA the quote must contain a number used by the answer or expression; for text answers it must share a token with the answer. |
| **claim traceability rate** | Claims with at least one valid citation whose numbers all follow from the cited evidence, divided by all claims. In TAT-QA, a text answer must appear inside a cited quote. A claim with no citations is not traceable. |
| **unsupported-number rate** | Numbers in the final insights and summary that cannot be traced, directly or derived, to *any* evidence the system saw, divided by all numbers. For TAT-QA it is the v1 metric: numeric answers not traceable to the whole context. |
| **confidence calibration** | ECE (10 equal bins) and Brier score of confidence against correctness. Correctness is TAT-QA EM = 1; for InsightBench it is summary judge ≥ 0.6, our threshold. `calibration_self` uses the confidence the model reports, which all systems are asked for. `calibration_det` is the agent's deterministic confidence. For TAT-QA it is 0.8 if the gate passes on the first round, 0.55 after a rewrite and 0.2 if it fails, capped at 0.1 when the answer is not traceable. For InsightBench it is 0.2 + 0.7 × (share of SQL that ran) × (share of claims surviving the gate), capped at 0.9. |
| **faithfulness (LLM judge, sample)** | On the first 30 InsightBench tasks for each system, the same model (Lightning) is given the system's evidence store (up to 9,000 characters) and its insights and summary, and rates 1–10 how well the claims and stated causes are supported. We report the mean /10. It is not deterministic and it is a self-family judge, so read it as indicative. |

Rates over citations, claims and numbers come with Wilson CIs. These units are not independent (they cluster within tasks), so the intervals are optimistic.

## dev run, Nebius Lightning (2026-10-22/23) — dev model, not the final evaluation

All systems on **Nebius `nvidia/Nemotron-3_5-Lightning`** (`LLM_PROVIDER=nebius`, single model for every step and for the judge). InsightBench: 100 tasks; TAT-QA dev: 150 questions (seeded sample). Scored with `python -m bench.report <file> --md`; bracketed ranges are 95% Wilson intervals. `errors` are counted inside `n` (an errored item scores as a miss). Raw records: `bench/results/insightbench-nebius-lightning-dev.jsonl`, `bench/results/tatqa-nebius-lightning-dev.jsonl` (resumed runs append; the report keeps the last record per system and id).

**InsightBench (n=100 per system)**

| system | n | errors | calls_per_item | sys_calls_per_item | tokens_per_item | nebius_usd_total | models | sec_per_item | insight_rouge1 | summary_rouge1 | summary_judge | judge>=0.6 | rouge>=0.25 | dropped_by_gate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agent | 100 | 0 | 5.9 | 4.9 | 16640 | 0.14 | ['nvidia/Nemotron-3_5-Lightning'] | 12.9 | 0.185 | 0.225 | 0.329 | 8/100 (0.04-0.15) | 22/100 (0.15-0.31) | 45 |
| rag | 100 | 0 | 2.0 | 1 | 5757 | 0.0513 | ['nvidia/Nemotron-3_5-Lightning'] | 3.9 | 0.166 | 0.221 | 0.299 | 8/100 (0.04-0.15) | 9/100 (0.05-0.16) | 0 |
| react | 100 | 0 | 7.9 | 6.9 | 12830 | 0.1025 | ['nvidia/Nemotron-3_5-Lightning'] | 10.0 | 0.174 | 0.229 | 0.293 | 1/100 (0.00-0.05) | 15/100 (0.09-0.23) | 0 |

**TAT-QA dev (n=150 per system)**

| system | n | errors | calls_per_item | sys_calls_per_item | tokens_per_item | nebius_usd_total | models | sec_per_item | EM | F1_mean | unsupported_numbers |
|---|---|---|---|---|---|---|---|---|---|---|---|
| agent | 150 | 0 | 1.4 | 1.4 | 1364 | 0.0159 | ['nvidia/Nemotron-3_5-Lightning'] | 1.1 | 57/150 (0.31-0.46) | 0.501 | 0/124 (0.00-0.03) |
| rag | 150 | 1 | 1 | 1 | 711 | 0.0088 | ['nvidia/Nemotron-3_5-Lightning'] | 0.7 | 51/150 (0.27-0.42) | 0.458 | 0/122 (0.00-0.03) |
| react | 150 | 0 | 3.1 | 3.1 | 2707 | 0.033 | ['nvidia/Nemotron-3_5-Lightning'] | 2.4 | 57/150 (0.31-0.46) | 0.487 | 0/127 (0.00-0.03) |

Notes:

- The dev run's Nebius cost, summed from the tables, is about $0.35 (InsightBench $0.29, TAT-QA $0.06), paid from promotional credit, under the hard guard (`NEBIUS_STRICT=1`, budget $5.20).
- One TAT-QA RAG item (`bdcabe8e-6738-47d3-8412-40e5e9a359d0`) fails deterministically with `TypeError: '<' not supported between instances of 'dict' and 'dict'`; a rerun on 2026-10-23 reproduced it. It is a harness bug, not a model error, and is still open.
- On InsightBench, the agent's gate dropped 45 unsupported insights across the 100 tasks.
- Intervals overlap on most metrics at this n; read the differences as indicative, not significant. The final evaluation is meant to run on the larger Nemotron model.

## Pilot (2026-10-22) — PILOT, tiny n, not results

The pilot ran on **Nebius `nvidia/Nemotron-3_5-Lightning`**: 3 InsightBench tasks (`flag-1..3`) and 15 TAT-QA dev questions (seeded random sample). Calls and tokens include the judge.

**InsightBench (n=3 per system)**

| system | n | errors | calls_per_item | sys_calls_per_item | tokens_per_item | nebius_usd_total | models | sec_per_item | insight_rouge1 | summary_rouge1 | summary_judge | judge>=0.6 | rouge>=0.25 | dropped_by_gate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agent | 3 | 0 | 7 | 6 | 20262 | 0.0051 | ['nvidia/Nemotron-3_5-Lightning'] | 12.2 | 0.164 | 0.178 | 0.433 | 0/3 (0.00-0.56) | 0/3 (0.00-0.56) | 0 |
| rag | 3 | 0 | 1.7 | 1 | 6322 | 0.0019 | ['nvidia/Nemotron-3_5-Lightning'] | 5.3 | 0.093 | 0.121 | 0.4 | 1/3 (0.06-0.79) | 0/3 (0.00-0.56) | 0 |
| react | 3 | 0 | 8 | 7 | 7607 | 0.0021 | ['nvidia/Nemotron-3_5-Lightning'] | 8.3 | 0.168 | 0.2 | 0.367 | 0/3 (0.00-0.56) | 0/3 (0.00-0.56) | 0 |

**TAT-QA dev (n=15 per system)**

| system | n | errors | calls_per_item | sys_calls_per_item | tokens_per_item | nebius_usd_total | models | sec_per_item | EM | F1_mean | unsupported_numbers |
|---|---|---|---|---|---|---|---|---|---|---|---|
| agent | 15 | 0 | 1.5 | 1.5 | 1153 | 0.0014 | ['nvidia/Nemotron-3_5-Lightning'] | 1.2 | 5/15 (0.15-0.58) | 0.407 | 0/12 (0.00-0.24) |
| rag | 15 | 0 | 1 | 1 | 587 | 0.0008 | ['nvidia/Nemotron-3_5-Lightning'] | 0.8 | 4/15 (0.11-0.52) | 0.341 | 0/12 (0.00-0.24) |
| react | 15 | 0 | 2.9 | 2.9 | 1874 | 0.0024 | ['nvidia/Nemotron-3_5-Lightning'] | 2.2 | 6/15 (0.20-0.64) | 0.537 | 1/12 (0.01-0.35) |


The **NVIDIA free tier, Super (`nemotron-3.5-super-vl-120b-a12b`)** pilot is partial: we stopped it when we switched to Nebius. It covered agent on flag-1/2, rag on flag-1 and react on flag-1:

| system | n | sec/item | tokens/item | insight R1 | summary R1 | summary judge |
|---|---|---|---|---|---|---|
| agent | 2 | 122 | 23.3k | 0.203 | 0.190 | 0.65 |
| rag | 1 | 117 | 5.7k | 0.231 | 0.196 | 0.40 |
| react | 1 | 24 | 4.0k | 0.203 | 0.253 | 0.60 |

The pilot spent about **$0.03 on Nebius**, including smoke calls and a discarded first attempt.

### Feasibility (extrapolated from the pilot, not measured at scale)

- **Nebius Lightning (dev)**:
  - InsightBench costs about $0.003 per task for all three systems combined (about 17 calls). 100 tasks ≈ **$0.30**, about 45 min sequential.
  - TAT-QA costs about $0.0003 per question for all three systems combined. 150 questions ≈ **$0.05**, about 10 min.
- **Super on Nebius (final)**: this is an estimate from the Lightning token counts at Super prices. InsightBench 100 tasks ≈ **$1.3** and TAT-QA 150 ≈ **$0.2**, so the full plan costs **< $2**, well under the $20 guard. Super latency per call is much higher; Nebius latency has not been measured.
- **Super on the NVIDIA free tier at ≤30 rpm**:
  - InsightBench needs about 17 calls per task for all systems, so 100 tasks ≈ 1.7k calls, a rate-limit floor of ≥ 57 min. Measured Super latency (24–122 s per item-system, about 260 s per task for all three) makes that about **7 h sequential** for 100 tasks, or about 2.2 h for 31.
  - TAT-QA needs about 5.4 calls per question for all systems, so 150 questions ≈ 810 calls, ≥ 27 min at 30 rpm.
  - The free tier is feasible overnight but slow. Nebius Super is cheaper in time for well under the budget.

### Known issues seen in the pilot

- Lightning sometimes stops at `finish_reason=length` when it cites long evidence lists. One RAG InsightBench item produced 0 insights for this reason.
- In TAT-QA, EM is strongly affected by `scale` (the official metric is scale-aware). Lightning often leaves scale empty even when prompted.
- If the gate's rewrite comes back empty or unparseable, the agent keeps the previous draft, and the gate still drops that draft's unsupported insights.
- The judge differs from the paper's logprob LLaMA-3 judge (see Scoring above).

## dev run v2 (post-audit), Nebius Lightning (2026-10-23) — dev model, not the final evaluation

Same model (`nvidia/Nemotron-3_5-Lightning`, Nebius, `NEBIUS_STRICT=1`), same 100 InsightBench tasks and 150 TAT-QA questions as v1, harness changes described above. v1 numbers below are the v1 records re-scored with the v2 report (`python -m bench.report`). Brackets: Wilson 95% CI for counts, bootstrap 95% CI for means. Both v2 runs finished with **0 errored items** (no error-row re-run was needed). Raw: `bench/results/*-nebius-lightning-dev-v2.jsonl`. Test suite: 70 passed.

### TAT-QA (n=150)

| system | EM v1 | EM v2 | F1 v1 | F1 v2 | EM raw (no post-step) v2 | errors v1→v2 |
|---|---|---|---|---|---|---|
| agent | 57 (0.31-0.46) | 77 (0.43-0.59) | 0.501 (0.420-0.578) | 0.638 (0.567-0.709) | 42 (0.21-0.36) | 0→0 |
| rag | 51 (0.27-0.42) | 69 (0.38-0.54) | 0.458 (0.380-0.538) | 0.565 (0.488-0.641) | 35 (0.17-0.31) | 1→0 |
| react | 57 (0.31-0.46) | 92 (0.53-0.69) | 0.487 (0.413-0.561) | 0.712 (0.642-0.779) | 44 (0.23-0.37) | 0→0 |

By answer type (EM, v1→v2): agent arithmetic 0.397→0.483, span 0.378→0.500, multi-span 0.385→0.769, count 0.200→0.400; rag arithmetic 0.368→0.379, span 0.324→0.500, multi-span 0.462→0.769, count 0→0; react arithmetic 0.483→0.810, span 0.324→0.500, multi-span 0.154→0.538, count 0.600→0.200 (n=5).

Track 02 (v2 only): citation precision agent 151/292 (0.46-0.57), rag 142/319 (0.39-0.50), react 122/297 (0.36-0.47); claim traceability agent 98/150 (0.57-0.72), rag 89/150 (0.51-0.67), react 82/150 (0.47-0.62); unsupported numbers 0 for all. Calibration (ECE/Brier): self-reported agent 0.461/0.462, rag 0.503/0.495, react 0.362/0.363 (all mean conf 0.98); agent deterministic 0.278/0.323.

### InsightBench (n=100, flag-36 not excluded in this sample)

| system | insight ROUGE-1 v1→v2 | summary ROUGE-1 v1→v2 | summary judge v1→v2 | judge≥0.6 v1→v2 | ROUGE≥0.25 v1→v2 |
|---|---|---|---|---|---|
| agent | 0.185 (0.171-0.199) → 0.188 (0.174-0.203) | 0.225 → 0.262 (0.250-0.273) | 0.329 (0.299-0.364) → 0.315 (0.280-0.354) | 8 → 7 | 22 → 19 |
| rag | 0.166 (0.151-0.181) → 0.124 (0.112-0.136) | 0.221 → 0.225 (0.208-0.242) | 0.299 → 0.272 (0.239-0.305) | 8 → 2 | 9 → 1 |
| react | 0.174 (0.161-0.188) → 0.160 (0.147-0.172) | 0.229 → 0.262 (0.250-0.274) | 0.293 → 0.304 (0.272-0.338) | 1 → 4 | 15 → 5 |

Agent SQL error rate: v1 171/1008 (0.15-0.19); v2 first try 191/1020 (0.17-0.21), after retry 139/1020 (0.12-0.16). React v2: 96/563 (0.14-0.20). Claims dropped by the agent gate: 45 → 27.

Track 02 (v2): 

| system | citation precision | claim traceability | unsupported-number rate | faithfulness judge (/10 scaled, first 30) | calib. self ECE/Brier | calib. det ECE/Brier |
|---|---|---|---|---|---|---|
| agent | 711/737 (0.95-0.98) | 480/530 (0.88-0.93) | 8/2046 (0.00-0.01) | 0.600 (0.543-0.650) | 0.834/0.760 | 0.705/0.588 |
| rag | 1374/1376 (0.99-1.00) | 44/237 (0.14-0.24) | 32/2004 (0.01-0.02) | 0.517 (0.434-0.597) | 0.879/0.795 | — |
| react | 137/160 (0.79-0.90) | 82/404 (0.17-0.24) | 194/2229 (0.08-0.10) | 0.593 (0.513-0.663) | 0.867/0.792 | — |

### Honest reading

- TAT-QA improved for all systems, mostly from the deterministic scale/format post-step (raw EM without it is *lower* than v1, e.g. agent 42 vs 57: the new prompt asks for unscaled numbers and relies on the post-step). **React now beats the agent on TAT-QA EM** (92 vs 77; CIs overlap), driven by arithmetic (0.81 vs 0.48).
- InsightBench did **not** improve on the content metrics: insight ROUGE is flat for the agent and **worse for rag and react**; judge means are within noise; the secondary threshold counts fell for agent (22→19), rag (9→1) and react (15→5) because v2 asks for longer prose insights. Summary ROUGE rose for all.
- Where the architecture does separate: on InsightBench the agent has 0.90 claim traceability vs 0.19 (rag) and 0.20 (react), and 0.4% unsupported numbers vs 9% for react. On TAT-QA the agent leads citation precision and traceability, with overlapping CIs.
- Calibration is poor everywhere on InsightBench (accuracy at the 0.6 judge threshold is 2-7%); the agent's deterministic confidence is better calibrated than self-reports but still overconfident. Citation/claim CIs are optimistic (clustered units). The faithfulness judge is the same model family.
- Spend: ledger $0.879 at resume → $1.023 after both v2 runs (all Nebius promo credit).

## Markovian control, sample (23 Oct 2026)

Model: Nebius `nvidia/Nemotron-3_5-Lightning` (`NEBIUS_STRICT=1`), deep path `nvidia/nemotron-3-super-120b-a12b` on Nebius. Sample sizes are small (TAT-QA dev 40 items, InsightBench 20); differences of a few items are within noise. Results: `bench/results/*-markov-sample.jsonl`, `*-markov-rerank-sample.jsonl`; table from `python -m bench.markov_report <files>`.

Systems: `agent` (before), `agent_mk` (Markov controller), `agent_mknv` (controller + NVIDIA classifier features), `agent_mkr` (controller + classifier + NVIDIA reranker relevance/citation check).

**What is our code.** The policy (`bench/markov.py`) is our own code. Each decision depends only on the current state and is logged as `{decision, state, action, reason, carryover}`. The vendored Meterless Markovian engine only provides chunked generation with `[STATE_CHECKPOINT]` carryover and `[TASK_COMPLETE]` stop; it has no routing/policy API. The controller uses its carryover format but does not call the vendored engine in the bench harness. **Bench only:** `app/pipeline.py` is not wired to the controller.

### TAT-QA (40 items)
| System | EM | F1 | Gate pass | Citations valid | Claims traceable | LLM calls/item | Wall s/item | Tokens/item | USD |
|---|---|---|---|---|---|---|---|---|---|
| agent | 0.525 | 0.632 | 0.775 | 0.627 | 0.625 | 1.35 | 1.10 | 1447 | 0.0044 |
| agent_mk | 0.625 | 0.732 | 0.425 | 0.385 | 0.550 | 2.35 | 1.92 | 2111 | 0.0067 |
| agent_mknv | 0.675 | 0.782 | 0.600 | 0.465 | 0.650 | 2.43 | 2.39 | 2176 | 0.0082 |
| agent_mkr | 0.625 | 0.732 | 0.625 | 0.395 | 0.625 | 2.55 | 2.97 | 2414 | 0.0096 |

Trade-off: accuracy rises (numeric route), but citation validity drops because the gate STOPs on quote-format failures instead of retrying. More calls and time per item. Reranker: 47 calls, 0.50 s/call including the 35 rpm pacing; it did not improve EM here.

### InsightBench (20 items)
| System | Insight ROUGE-1 | Summary ROUGE-1 | Summary judge | Faithfulness | Numbers unsupported | Citations valid | Claims traceable | SQL error rate | LLM calls/item | Wall s/item | Tokens/item | USD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agent | 0.201 | 0.274 | 0.390 | 0.590 | 0.006 | 0.980 | 0.938 | 0.037 | 6.05 | 13.9 | 27257 | 0.0427 |
| agent_mk | 0.192 | 0.263 | 0.385 | 0.568 | 0.006 | 0.953 | 0.769 | 0.085 | 4.00 | 10.4 | 11813 | 0.0222 |
| agent_mknv | 0.203 | 0.277 | 0.410 | 0.605 | 0.000 | 0.991 | 0.901 | 0.083 | 3.70 | 8.4 | 10139 | 0.0269 |
| agent_mkr | 0.199 | 0.266 | 0.380 | 0.595 | 0.000 | 0.966 | 0.876 | 0.085 | 4.10 | 34.2 | 11433 | 0.0329 |

The controller cuts LLM calls by about 35-40 % and tokens by about 60 % at similar quality; the classifier version is on par with or slightly above the baseline. The SQL error rate is higher because early stop/give-up keeps failed queries in the count. Reranker citation check: 97 calls, 48 SUPPORTED / 49 WEAK, logged only (never drops claims, uncalibrated on this bench); 1.41 s/call wall including pacing.

### NVIDIA models used (free only)
- `nvidia/prompt-task-and-complexity-classifier` (open weights, CPU, `scripts/nv_classify.py`): features precomputed into `bench/features/`. 40 TAT-QA items took 181 s and 20 InsightBench items 101 s on CPU, including model load. Thresholds are the top quartile of each bench's own complexity distribution (no labels): TAT-QA 0.145, InsightBench 0.258.
- `nvidia/llama-nemotron-rerank-vl-1b-v2` via `ai.api.nvidia.com/v1/retrieval/.../reranking`, with a sigmoid on the logits. `RELEVANCE_MIN=0.05` was calibrated on held-out TAT-QA dev items 41-100, never on the evaluated 40. The requested `llama-nemotron-rerank-1b-v2`, `llama-3.2-nemoretriever-500m-rerank-v2` and `llama-3.2-nv-rerankqa-1b-v2` return HTTP 410 (end of life). `nemotron-3.5-rerank-8b` was not tested.
