#!/bin/bash
# Markov control battery n=100. usage: TAG=pre|post SRC=<worktree> SYS=agent_mk BUDGET=<abs ledger USD> bench_battery.sh
cd "${SRC:?}"
export LLM_PROVIDER=nebius NEBIUS_MODEL=nvidia/Nemotron-3_5-Lightning NEBIUS_STRICT=1 MODEL_TIMEOUT_S=90
export NEBIUS_BUDGET_USD=${BUDGET:?}
OUT=/workspace/vw-bench/bench/results/battery
for pass in 1 2; do
for b in ${BENCHES:-tatqa insightbench}; do
/workspace/vw-bench/.venv/bin/python -m bench.run --bench $b --systems ${SYS:?} --limit ${LIMIT:-100} ${IDS:+--ids $IDS} --max-calls 4000 --max-calls-item ${MCI:-40} --rpm 120 --faith-sample 100 ${NOJUDGE:+--no-judge} --out $OUT/$b-${TAG:?}-$SYS.jsonl || exit 1
done; done
echo ALLDONE
