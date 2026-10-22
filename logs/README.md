# logs/
Written at runtime (to `logs/`, or to `VA_LOG_DIR` if set). Runtime files are gitignored; only `logs/examples/` is committed. Logs never contain secrets.

## Per-run files
- `trace-<run_id>.jsonl`: one JSON object per step: agent, action, input/output summary, target agent, retries, status. Includes Zetaris/DuckDB queries, Meterless calls, `data_fallback` (SAMPLE MODE) and `meterless_unavailable` events.
- `hmem-ledger-<run_id>.jsonl`: Meterless H-MEM trust ledger (record creation, reads, support/refute edges).
- `memo-<run_id>.md` / `.pdf`, `result-<run_id>.json`, `report-<run_id>.json`.
- The Markovian run record (chunks, carryover, estimated tokens) is inside the result JSON and the trace.

## Committed examples
`logs/examples/` holds the trace, memo and H-MEM ledger for the three examples in `input_examples/` (SAMPLE_MODE, synthetic data).
