#!/bin/bash
# PREREG.md final evaluation: TAT-QA tatqa_test500_v1, ONE run per arm, T=0, frozen config bench/freeze/test500_v1.json.
# NVIDIA free endpoint ($0). Never rerun after results are seen. Aborts on a dirty tree (bench/run.py).
# usage: bash bench_test500.sh            (arms: agent_mk then rag; 3 resume passes each for errored items)
set -e
cd "$(dirname "$0")"
PY=${PY:-python}
export LLM_PROVIDER=nvidia SAMPLE_MODE=false MODEL_TIMEOUT_S=120 LLM_CACHE=0 BENCH_SINGLE_MODEL=1 CR_USE_CALIB=0 AUDIT_TRACE=1
export REASONING_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b FAST_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b DEEP_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
export NEBIUS_STRICT=1
S=bench/splits/tatqa_test500_v1.json
OUTD=bench/results/test500
mkdir -p $OUTD
for SYS in agent_mk rag; do
  for pass in 1 2 3; do
    $PY -m bench.run --bench tatqa --systems $SYS --split-file $S --repeat 0 --no-judge --max-calls 6000 --rpm 8.5 \
      --out $OUTD/tatqa-test500-$SYS-r0.jsonl --trace-dir $OUTD/traces-$SYS || true
  done
done
HELDOUT_SPLIT=$S $PY -m bench.heldout_report $OUTD --md > $OUTD/REPORT.md
HELDOUT_SPLIT=$S $PY -m bench.heldout_report $OUTD > $OUTD/report.json
echo ALLDONE
