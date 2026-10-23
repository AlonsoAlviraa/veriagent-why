#!/bin/bash
# Markovian control sample eval (agent baseline vs agent_mk vs agent_mknv). Hard cap: BUDGET (absolute ledger USD).
cd /workspace/vw-bench
export LLM_PROVIDER=nebius NEBIUS_MODEL=nvidia/Nemotron-3_5-Lightning NEBIUS_STRICT=1 MODEL_TIMEOUT_S=90
export NEBIUS_BUDGET_USD=${BUDGET:?}
for pass in 1 2; do
.venv/bin/python -m bench.run --bench tatqa --systems agent_mkr --limit 40 --max-calls 1500 --rpm 120 --out bench/results/tatqa-markov-rerank-sample.jsonl || exit 1
.venv/bin/python -m bench.run --bench insightbench --systems agent_mkr --limit 20 --max-calls 2500 --rpm 120 --faith-sample 20 --out bench/results/insightbench-markov-rerank-sample.jsonl || exit 1
done
echo ALLDONE
