# Diagram v6.2 → code traceability

Each box and arrow of `veriagent_why_arch_v6.2.png` maps to the code that implements it, the trace event that proves it ran, and the test that checks it.
The single end-to-end proof is `python scripts/e2e_live.py`. It goes User → UI → API → … → memo over real HTTP and exits non-zero if any box below emits no trace event.

| Diagram element | Code (file → function) | Trace event (`logs/trace-<run_id>.jsonl`) | Test |
|---|---|---|---|
| User (ops analyst) → question | `app/static/index.html` (question box); `input_examples/*.json` | — | `tests/test_api.py::test_async_run_trace_result_whatif_pdf`; `scripts/e2e_live.py` |
| UI, separate port | `app/ui.py` → `index`, `proxy` (:8501, proxies `/api/*` to :8000) | — | `scripts/e2e_live.py` (all calls go through the UI proxy) |
| API (programmatic entry) | `app/api.py` → `run_endpoint` (`POST /run`), `start` (`POST /runs`), `trace`, `result` | — | `tests/test_api.py` |
| Meterless orchestrator | `app/pipeline.py` → `run`, `_run`; `app/meterless.py` → `Bridge` (node bridge to the vendored engines) | `orchestrator/start`, `orchestrator/backend` (`meterless: bridge`) | `tests/test_e2e_arch.py::test_sample_run_touches_every_box_and_writes_artifacts` |
| Provider path Nightshift / NVIDIA / sample | `app/llm.py` → `complete` (`LLM_PROVIDER`), `_post` (pacer + 429/5xx retry) | `*/model_call` with `provider`, `model` | `tests/test_llm_mock.py`, `tests/test_e2e_arch.py::test_live_path_calls_each_llm_box_s1_in_parallel`, `tests/test_nvidia_smoke.py` |
| Planner (Super 3.5) | `app/agents/core.py` → `Planner.plan`; `app/agents/llm_steps.py` → `plan` | `planner/hypotheses`, `planner/model_call` | `tests/test_hypothesis_families.py`, `tests/test_e2e_arch.py` |
| SQL plans → Zetaris SQL (5 views) | `app/agents/core.py` → `Retriever.retrieve`; `app/adapters/zetaris.py` → `ZetarisJdbcBackend` (JDBC), `SampleBackend` (DuckDB offline) | `retriever/retrieved`; `orchestrator/backend` names the backend | `tests/test_zetaris_jdbc.py::test_pipeline_through_jdbc_backend` (fake JDBC conn) |
| + BM25 text | `app/bm25.py`; used in `Retriever.retrieve` over `v_tickets.text` | `retriever/retrieved` | `tests/test_pipeline.py` |
| raw rows → S1 Filter (Lightning 3.5, no-think, parallel) | `app/agents/core.py` → `S1Filter.run`; `llm_steps.s1_scores` (ThreadPoolExecutor(8)); `enable_thinking: False` in `llm.complete` | `s1_filter/filtered` (projected vs actual tokens), `s1_filter/model_call` (`batch` > 1) | `tests/test_e2e_arch.py::test_live_path_calls_each_llm_box_s1_in_parallel` |
| kept → Evidence Eval (re-queries Zetaris) | `app/agents/core.py` → `EvidenceEvaluator.evaluate` (own `db.query`, `evaluator_requery` nodes); `llm_steps.verdict` | `evidence_evaluator/verdicts`, `…/model_call` | `tests/test_pipeline.py`, `tests/test_robustness.py` |
| Arrow: evidence gap / trap refuted → revise plan + requery (max 3) | `pipeline._run` → `investigate_round`, driven by `markovian.run` (`maxChunks=CAPS["evaluator_rounds"]=3`) | `evidence_evaluator/send_back_to_planner`, then `planner/hypotheses` with `revised: true` | `tests/test_markovian.py`, `tests/test_e2e_arch.py` |
| verdicts → Cause Analyst (Super 3.5) | `app/agents/core.py` → `CauseAnalyst.analyse`; `llm_steps.label` | `cause_analyst/ranked`, `…/model_call` | `tests/test_robustness.py`, `tests/test_e2e_arch.py` |
| causes → Writer (Super 3.5) | `app/agents/core.py` → `Writer.write`; `llm_steps.narrative` | `writer/claims`, `writer/model_call` | `tests/test_llm_mock.py` |
| claims → Claim Gate (deterministic) | `app/agents/core.py` → `ClaimGate.check`; `app/checks/claims.py` (shared with the eval) incl. `check_narrative` | `claim_gate/checked` | `tests/test_claim_gate.py` |
| Arrow: claim fails check → rewrite (max 2) | `pipeline._run` gate loop (`CAPS["claim_gate_rounds"]=2`) | `claim_gate/send_back_to_cause_analyst`, then a second `cause_analyst/ranked` | `tests/test_e2e_arch.py::test_claim_gate_loops_back_to_cause_analyst`, `tests/test_llm_mock.py::test_hallucinated_number_is_blocked` |
| verified → Memo (ranked causes, confidence 0–100 by code) | `app/memo.py` → `render_memo`; `app/confidence.py` → `confidence`; `app/pdf.py` → `memo_pdf`; `app/api.py` → `memo`, `memo_pdf` | `orchestrator/end` (status, confidence) | `tests/test_confidence.py`, `tests/test_api.py` |
| Arrow: memo (MD/PDF + JSON) with row-ID citations → UI | `GET /memo/{id}.md\|.pdf`, `GET /runs/{id}`, `GET /rows/{view}/{id}` (click-through) | — | `scripts/e2e_live.py`, `tests/test_api.py` |
| Caps or 8-min timeout → partial memo "unresolved", confidence ≤ 40 | `config.TIMEOUTS["run_s"]=480`; `llm.set_deadline` / `remaining` (model calls fail fast past the deadline → deterministic fallback); `pipeline._run` (`deadline_hit`, `status="partial"`); `confidence(partial=True)` | `orchestrator/deadline_hit`, `orchestrator/end` with `status: partial` | `tests/test_e2e_arch.py::test_run_deadline_gives_partial_unresolved_capped`, `::test_deadline_makes_model_calls_fail_fast` |
| read / write → Meterless engines: H-MEM evidence graph | `app/memory.py` → `HMem` (bridge or local fallback); ledger to `logs/hmem-ledger-<id>.jsonl` | `orchestrator/backend` (`meterless`) | `tests/test_hmem_graph.py` |
| Markovian (chunked multi-round carryover) | `app/meterless.py` `Bridge.call("markovian.run", on_step=…)` | `markovian/run` (chunks, carryover, tokens) | `tests/test_markovian.py` |
| Observability: JSONL trace | `app/trace.py` → `Tracer` (secret keys redacted) | every line | all tests above |
| Observability: H-MEM ledger | `pipeline._run` writes `logs/hmem-ledger-<id>.jsonl` | `evidence_graph.hmem_ledger_file` in result | `tests/test_hmem_graph.py` |
| Observability: token / cost report | `app/report.py` → `build`, `to_md`; `logs/report-<id>.json`; section in the memo | `observability/run_report` | `tests/test_e2e_arch.py::test_sample_run_touches_every_box_and_writes_artifacts` |
| SAMPLE_MODE=true offline | `config.sample_mode` / `provider()`; `SampleBackend` (DuckDB, same SQL); deterministic agent paths | `orchestrator/start` `provider: sample` | whole suite (CI runs offline); `tests/test_hmem_graph.py::test_sample_mode_is_deterministic` |
| eval: 6 dev / 18 test (demo trap dev only) | `eval/eval.py`, `eval/baseline_rag.py`, `eval/SPLITS*.sha256` | `logs/trace-eval-*.jsonl` | `tests/test_eval_wilson.py` |

## Known gaps (honest)
- **Nightshift**: the code path exists and is tested against a local mock OpenAI-compatible server. It has not run against a real Nightshift endpoint from this box.
- **Zetaris JDBC**: tested with a fake JDBC connection that runs the rendered SQL on DuckDB. It has not run against a live Zetaris instance; see `docs/RUN_WINDOWS.md`.
- **Deadline scope**: the deadline is process-global (`llm._DEADLINE`). Two concurrent runs in one API process share it, so the later run's deadline wins. The demo runs one at a time.
- **Cost**: tokens come from the provider's `usage` field. On the NVIDIA free endpoint and the sample provider, cost is reported as 0 EUR. No list price is invented unless you pass `MODEL_PRICE_EUR_PER_MTOK`.
