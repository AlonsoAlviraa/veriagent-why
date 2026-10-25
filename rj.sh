#!/bin/bash
# usage: rj.sh <name> ; rejudges bench/results/battery/insightbench-<name>.jsonl with Super
cd /workspace/vw-bench
export NEBIUS_STRICT=1 NEBIUS_BUDGET_USD=3.19 LLM_PROVIDER=nebius MODEL_TIMEOUT_S=90
B=bench/results/battery
exec .venv/bin/python -m bench.rejudge $B/insightbench-$1.jsonl $B/insightbench-$1.rj.jsonl
