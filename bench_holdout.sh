#!/bin/bash
# Held-out reruns (docs/HELDOUT_RESULTS.md). NVIDIA free endpoint, $0. usage: ROOT=<repo or worktree> SYS=agent_mk TAG=fix REP=0 RPM=8.5 bench_holdout.sh
# Aborts on a dirty tree (bench/run.py); baseline arm runs from a clean worktree of feat/markov-control.
set -e
cd ${ROOT:-/workspace/vw-bench}
export LLM_PROVIDER=nvidia SAMPLE_MODE=false MODEL_TIMEOUT_S=120
export REASONING_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b FAST_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b DEEP_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
H=/workspace/vw-bench/bench/splits/holdout_v1.json
IDS=$(python3 -c "import json;print(','.join(json.load(open('$H'))['ids']))")
OUT=/workspace/vw-bench/bench/results/holdout/tatqa-${TAG:?}-${SYS:?}-r${REP:?}.jsonl
mkdir -p $(dirname $OUT)
for pass in 1 2 3; do  # resume passes (errored items are retried)
  if [ -n "$BASELINE" ]; then
    TATQA_SPLIT=test_gold /workspace/vw-bench/.venv/bin/python -m bench.run --bench tatqa --systems $SYS --ids "$IDS" --max-calls 3000 --rpm ${RPM:-8.5} --out $OUT --trace-dir /workspace/vw-bench/bench/results/holdout/traces-$TAG-$SYS-r$REP
  else
    /workspace/vw-bench/.venv/bin/python -m bench.run --bench tatqa --systems $SYS --split-file $H --repeat $REP --max-calls 3000 --rpm ${RPM:-8.5} --out $OUT --trace-dir /workspace/vw-bench/bench/results/holdout/traces-$TAG-$SYS-r$REP
  fi
done
echo ALLDONE
