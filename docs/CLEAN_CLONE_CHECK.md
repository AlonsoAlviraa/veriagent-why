# Clean-clone check

Date: 25 Oct 2026, about 12:29 Madrid (CET). Script: [`scripts/clean_clone_e2e.sh`](../scripts/clean_clone_e2e.sh).

- Source: fresh `git clone` of `https://github.com/AlonsoAlviraa/veriagent-why.git`, checked out at `main` = `0b7aac6`.
- Setup: empty `.env`; `NVIDIA_API_KEY`, `NEBIUS_API_KEY` and `SAMPLE_MODE` unset; Python 3.13.5 on Linux.
- Pip caveat: the pip wheel cache on this machine was warm, so the install times are a lower bound. A cold install will be slower.

## Steps and timings

| Step (README order) | Exit code | Wall time (s) |
|---|---|---|
| `git clone` | 0 | 2.3 |
| `python3 -m venv .venv` | 0 | 1.6 |
| `pip install -r requirements.txt` (what `make setup` does) | 0 | 5.0 (warm cache) |
| `python run.py --input input_examples/example_1.json` | 0 | 0.8 |
| same, second run | 0 | 0.5 |
| `example_2.json` | 0 | 0.5 |
| same, second run | 0 | 0.5 |
| `example_3.json` | 0 | 0.4 |
| same, second run | 0 | 0.5 |
| `make run` | 0 | 0.5 |
| `make test` with only `requirements.txt` | **2 (6 failed, 328 passed, 1 skipped, 49 xfailed)** | 35.7 |
| `pip install -r bench/requirements-bench.txt` | 0 | 9.9 (warm cache) |
| `make test` with the bench requirements | 0 (334 passed, 1 skipped, 49 xfailed) | 29.3 |
| `make scan` (secret scan) | 0 (clean) | 0.7 |

## The three demo scenarios (SAMPLE_MODE)

| Scenario | Status | Top cause | Same as committed `output_examples/`? | Rerun identical? |
|---|---|---|---|---|
| example_1 | success | carrier_sla_breach | yes | yes |
| example_2 | success | carrier_sla_breach | yes | yes |
| example_3 | partial | none (as committed) | yes | yes |

- "Same" and "identical" mean equal on every field except the 3 run-specific ones: `trace_id`, `execution_time_seconds` and `run_report.wall_clock_s`. Log paths are also normalised.
- Every run prints `SAMPLE MODE (...): no Zetaris; data is the SYNTHETIC DuckDB snapshot`. The input examples set `options.sample_mode`, so the reason shown is "set explicitly".
- This check is now a test: `tests/battery/test_sample_mode_e2e_battery.py` (15 tests).

## Finding (needs a decision)

**`make setup` followed by `make test` fails on a clean clone.** `make setup` installs only `requirements.txt`. Six tests need `rouge_score` and other packages from `bench/requirements-bench.txt`. The failing tests are:
- test_bench_offline insightbench
- test_bench_v2 report
- test_markov_control offline
- 2 in test_trace_fixes
- test_verify_v2 traces

`scripts/clean_clone_check.sh` already installs both files, so `make clean-check` passes.

There are two possible fixes, and both are outside this PR's scope (Makefile/README):
- add `-r bench/requirements-bench.txt` to `make setup`, or
- mark those 6 tests `skipif` when `rouge_score` is missing.
