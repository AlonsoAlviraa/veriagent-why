#!/usr/bin/env bash
# Timed clean-clone end-to-end check following the README Quick start, offline (SAMPLE_MODE, empty .env).
# Usage: scripts/clean_clone_e2e.sh <git-url-or-path> <ref> <out-dir>
set -uo pipefail
SRC="$1"; REF="$2"; OUT="$3"; mkdir -p "$OUT"; TMP="$(mktemp -d)"
t() { local n="$1"; shift; local s=$(date +%s.%N); "$@" > "$OUT/$n.log" 2>&1; local rc=$?; local e=$(date +%s.%N)
      printf '%s\t%s\t%.1f\n' "$n" "$rc" "$(awk "BEGIN{print $e - $s}")" | tee -a "$OUT/timings.tsv"; return 0; }
: > "$OUT/timings.tsv"
t clone git clone -q "$SRC" "$TMP/repo"
cd "$TMP/repo" && git checkout -q "$REF" && git rev-parse HEAD > "$OUT/head.txt"
: > .env
t venv python3 -m venv .venv
t pip_requirements .venv/bin/pip install -q -r requirements.txt
for i in 1 2 3; do
  t "run_example_$i" env -u NVIDIA_API_KEY -u NEBIUS_API_KEY -u SAMPLE_MODE .venv/bin/python run.py --input input_examples/example_$i.json
  cp "$OUT/run_example_$i.log" "$OUT/example_$i.out"
  t "run_example_${i}_again" env -u NVIDIA_API_KEY -u NEBIUS_API_KEY -u SAMPLE_MODE .venv/bin/python run.py --input input_examples/example_$i.json
done
t make_run make run PY=.venv/bin/python
t make_test_requirements_only make test PY=.venv/bin/python
t pip_bench .venv/bin/pip install -q -r bench/requirements-bench.txt
t make_test_with_bench_reqs make test PY=.venv/bin/python
t make_scan make scan PY=.venv/bin/python
echo "$TMP/repo" > "$OUT/repo_path.txt"
