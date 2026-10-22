# Request/response contract (from the technical-execution guide §2)
Request: `{"run_id": "...", "input": {"query": "..."}, "options": {"sample_mode": false}}`
Success: `{"run_id","status":"success","output":{"summary","recommendations","artifacts"},"agents":[{name,role}],"trace_id","log_file":"logs/trace-<run_id>.jsonl","execution_time_seconds"}`
Error: `{"run_id","status":"error","error":{"type","message","recoverable"},"trace_id","execution_time_seconds"}`
Timeouts: external API 10–30 s · model 30–90 s · agent iteration 1–3 min · full run target 5–10 min.
