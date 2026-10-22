# logs/
Written at runtime to stdout and to this folder. Never contains secrets (mask keys: `sk-...redacted`).

## Per-run trace: `trace-<run_id>.jsonl`
One JSON object per line (recommended format, technical-execution guide §8):
```json
{"timestamp":"2026-10-24T18:42:11Z","run_id":"demo-001","agent_name":"Planner","action":"delegate_task","input_summary":"...","output_summary":"...","target_agent":"Retriever","confidence":0.91,"retry_count":0,"status":"success"}
```
It should show: which agents ran and what each was asked; handoffs; critique/validation; refinement loops; retries, fallbacks, recovery; calls to Zetaris and Meterless; final synthesis; errors and what happened next.

## Meterless engine evidence (TODO)
- `hmem-audit-<run_id>.jsonl`: H-MEM trust ledger (create/read/update/delete, promote/demote/merge, conflicts) plus retrieval traces
- `markovian-<run_id>.jsonl`: per-chunk telemetry plus a projected-vs-actual token savings report
