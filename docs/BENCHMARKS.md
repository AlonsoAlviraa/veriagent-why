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
