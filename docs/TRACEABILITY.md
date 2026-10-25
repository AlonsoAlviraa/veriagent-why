# Final architecture diagram → code traceability

Each box and arrow of `docs/diagrams/veriagent_why_arch_FINAL.png` (v6.2 plus the Agentic Retriever loop, NVIDIA embeddings and hybrid fusion) maps to the code that implements it, the trace event that proves it ran, and the test that checks it.
The single end-to-end proof is `python scripts/e2e_live.py`. It goes User → UI → API → … → memo over real HTTP and exits non-zero if any box below emits no trace event.

| Diagram element | Code (file → function) | Trace event (`logs/trace-<run_id>.jsonl`) | Test |
|---|---|---|---|
| User (ops analyst) → question | `app/static/index.html` (question box); `input_examples/*.json` | — | `tests/test_api.py::test_async_run_trace_result_whatif_pdf`; `scripts/e2e_live.py` |
| UI, separate port | `app/ui.py` → `index`, `proxy` (:8501, proxies `/api/*` to :8000) | — | `scripts/e2e_live.py` (all calls go through the UI proxy) |
| API (programmatic entry) | `app/api.py` → `run_endpoint` (`POST /run`), `start` (`POST /runs`), `trace`, `result` | — | `tests/test_api.py` |
| Meterless orchestrator | `app/pipeline.py` → `run`, `_run`; `app/meterless.py` → `Bridge` (node bridge to the vendored engines) | `orchestrator/start`, `orchestrator/backend` (`meterless: bridge`) | `tests/test_e2e_arch.py::test_sample_run_touches_every_box_and_writes_artifacts` |
| Provider path Nightshift / NVIDIA / sample | `app/llm.py` → `complete` (`LLM_PROVIDER`), `_post` (pacer + 429/5xx retry) | `*/model_call` with `provider`, `model` | `tests/test_llm_mock.py`, `tests/test_e2e_arch.py::test_live_path_calls_each_llm_box_s1_in_parallel`, `tests/test_nvidia_smoke.py` |
| Planner (Super 3.5) | `app/agents/core.py` → `Planner.plan`; `app/agents/llm_steps.py` → `plan` | `planner/hypotheses`, `planner/model_call` | `tests/test_hypothesis_families.py`, `tests/test_e2e_arch.py` |
| SQL plans → Agentic Retriever (Lightning 3.5 tool loop, per hypothesis) | `app/retrieval/agentic.py` → `AgenticRetriever.retrieve`; mandatory seed tool per hypothesis, then up to 2 model steps (`llm_steps.retrieval_step`, JSON `{sufficient, tool, args, why}`), always ends with a policy `text_search` | `retriever/tool_call`, `retriever/agent_decision`, `retriever/repeat_call_stopped`, `retriever/retrieved` | `tests/test_agentic_rag.py::test_sample_pipeline_uses_agentic_retriever_and_reports_embedder` |
| Tool whitelist (no free-form SQL) | `agentic.TOOLS`: `segment_stats`, `drill_down`, `promotions_overlap`, `text_search`; args checked against DISTINCT values in the data, dates clipped to the period, query string sanitised | `retriever/tool_rejected` | `tests/test_agentic_rag.py::test_tool_whitelist_rejects_unknown_tools_bad_values_and_sql`, `::test_agent_sufficient_stops_and_invalid_tool_is_rejected_and_traced` |
| Loop caps: ≤2 steps/hyp · ≤8 calls/round · token budget | `agentic.CAPS` (`model_steps_per_hyp`=2, `model_calls_per_round`=8, `tokens_per_round`=8000) | `retriever/cap_reached` | `tests/test_agentic_rag.py::test_agent_loop_caps_steps_per_hypothesis_and_round` |
| Deterministic fallback | model failure / invalid JSON → policy tools only (same path as SAMPLE_MODE) | `retriever/model_step_failed` | `tests/test_agentic_rag.py::test_model_failure_falls_back_to_deterministic_policy_same_as_sample` |
| Tools: Zetaris SQL templates (5 views) | `app/agents/core.py` → `Retriever.chunks_for`; `app/adapters/zetaris.py` → `ZetarisJdbcBackend` (JDBC), `SampleBackend` (DuckDB offline) | `retriever/tool_call`; `orchestrator/backend` | `tests/test_zetaris_jdbc.py::test_pipeline_through_jdbc_backend` |
| Hybrid text search: BM25 + NVIDIA embed (RRF) | `app/retrieval/hybrid.py` → `search`, `rrf` (k=60); `app/bm25.py`; `app/embeddings.py` → `embed` (`nvidia/nemotron-3-embed-1b`, passage/query input types, disk cache `data/emb_cache/`) | `retriever/tool_call` (`text_search`); `retrieval.embed_*` in result | `tests/test_agentic_rag.py::test_rrf_fusion_math_and_ids_kept`, `::test_nvidia_embedder_mocked_http_input_type_and_disk_cache`, `::test_hybrid_falls_back_to_bm25_when_embedder_fails` |
| Hash embed offline | `embeddings.hash_embed` (Python port of the vendored FNV-1a 64-dim embedder); `EMBED_PROVIDER=hash` forces it | `retrieval.embed_backend: hash` | `tests/test_agentic_rag.py::test_hash_embedder_deterministic_unit_and_matches_vendored_contract` |
| raw rows → S1 Filter (Lightning 3.5, no-think, parallel) | `app/agents/core.py` → `S1Filter.run`; `llm_steps.s1_scores` (ThreadPoolExecutor(8)); `enable_thinking: False` in `llm.complete` | `s1_filter/filtered` (projected vs actual tokens), `s1_filter/model_call` (`batch` > 1) | `tests/test_e2e_arch.py::test_live_path_calls_each_llm_box_s1_in_parallel` |
| kept → Evidence Eval (re-queries Zetaris) | `app/agents/core.py` → `EvidenceEvaluator.evaluate` (own `db.query`, `evaluator_requery` nodes); `llm_steps.verdict` | `evidence_evaluator/verdicts`, `…/model_call` | `tests/test_pipeline.py`, `tests/test_robustness.py` |
| Arrow: evidence gap / trap refuted → revise plan + requery (max 3) | `pipeline._run` → `investigate_round`, driven by `markovian.run` (`maxChunks=CAPS["evaluator_rounds"]=3`) | `evidence_evaluator/send_back_to_planner`, then `planner/hypotheses` with `revised: true` | `tests/test_markovian.py`, `tests/test_e2e_arch.py` |
| verdicts → Cause Analyst (Super 3.5) | `app/agents/core.py` → `CauseAnalyst.analyse`; `llm_steps.label` | `cause_analyst/ranked`, `…/model_call` | `tests/test_robustness.py`, `tests/test_e2e_arch.py` |
| causes → Writer (Super 3.5) | `app/agents/core.py` → `Writer.write`; `llm_steps.narrative` | `writer/claims`, `writer/model_call` | `tests/test_llm_mock.py` |
| claims → Traceability Check (deterministic) | `app/agents/core.py` → `ClaimGate.check`; `app/checks/claims.py` (shared with the eval) incl. `check_narrative` | `claim_gate/checked` | `tests/test_claim_gate.py` |
| Arrow: claim fails check → rewrite (max 2) | `pipeline._run` gate loop (`CAPS["claim_gate_rounds"]=2`) | `claim_gate/send_back_to_cause_analyst`, then a second `cause_analyst/ranked` | `tests/test_e2e_arch.py::test_claim_gate_loops_back_to_cause_analyst`, `tests/test_llm_mock.py::test_hallucinated_number_is_blocked` |
| verified → Memo (ranked causes, confidence 0–100 by code) | `app/memo.py` → `render_memo`; `app/confidence.py` → `confidence`; `app/pdf.py` → `memo_pdf`; `app/api.py` → `memo`, `memo_pdf` | `orchestrator/end` (status, confidence) | `tests/test_confidence.py`, `tests/test_api.py` |
| Arrow: memo (MD/PDF + JSON) with row-ID citations → UI | `GET /memo/{id}.md\|.pdf`, `GET /runs/{id}`, `GET /rows/{view}/{id}` (click-through) | — | `scripts/e2e_live.py`, `tests/test_api.py` |
| Caps or 8-min timeout → partial memo "unresolved", confidence ≤ 40 | `config.TIMEOUTS["run_s"]=480`; `llm.set_deadline` / `remaining` (model calls fail fast past the deadline → deterministic fallback); `pipeline._run` (`deadline_hit`, `status="partial"`); `confidence(partial=True)` | `orchestrator/deadline_hit`, `orchestrator/end` with `status: partial` | `tests/test_e2e_arch.py::test_run_deadline_gives_partial_unresolved_capped`, `::test_deadline_makes_model_calls_fail_fast` |
| read / write → Meterless engines: H-MEM evidence graph | `app/memory.py` → `HMem` (bridge or local fallback); ledger to `logs/hmem-ledger-<id>.jsonl` | `orchestrator/backend` (`meterless`) | `tests/test_hmem_graph.py` |
| H-MEM: hypothesis → tool call → evidence; real embeddings when live | every tool call is a `retrieval` node with a `retrieved_for` edge; `HMem.flush()` batch-embeds buffered records with the same embedder (bridge `hmem.add {embedding}`, `hmem.query {queryEmbedding}`; vendored change declared in `vendor/meterless/README.md`) | `retrieval.hmem_embedder`, `hmem_embed_stats` in result | `tests/test_agentic_rag.py::test_every_tool_call_is_an_hmem_retrieval_node` |
| Markovian (chunked multi-round carryover) | `app/meterless.py` `Bridge.call("markovian.run", on_step=…)` | `markovian/run` (chunks, carryover, tokens) | `tests/test_markovian.py` |
| Observability: JSONL trace (every tool call) | `app/trace.py` → `Tracer` (secret keys redacted) | every line, incl. each `retriever/tool_call` | all tests above |
| Observability: H-MEM ledger | `pipeline._run` writes `logs/hmem-ledger-<id>.jsonl` | `evidence_graph.hmem_ledger_file` in result | `tests/test_hmem_graph.py` |
| Observability: token / cost report | `app/report.py` → `build`, `to_md`; `logs/report-<id>.json`; section in the memo | `observability/run_report` | `tests/test_e2e_arch.py::test_sample_run_touches_every_box_and_writes_artifacts` |
| SAMPLE_MODE=true offline | `config.sample_mode` / `provider()`; `SampleBackend` (DuckDB, same SQL); deterministic agent paths | `orchestrator/start` `provider: sample` | whole suite (CI runs offline); `tests/test_hmem_graph.py::test_sample_mode_is_deterministic` |
| eval: 6 dev / 18 test (demo trap dev only) | `eval/eval.py`, `eval/baseline_rag.py`, `eval/SPLITS*.sha256` | `logs/trace-eval-*.jsonl` | `tests/test_eval_wilson.py` |

## Known gaps (honest)
- **Embeddings**: `llama-3.2-nv-embedqa-1b-v2` and `nv-embedqa-e5-v5` return 410 Gone on the free endpoint, so `nvidia/nemotron-3-embed-1b` (2048 dims) is used. Nightshift has no embeddings route; with `LLM_PROVIDER=nightshift` embeddings still go to NVIDIA if `NVIDIA_API_KEY` is set, else hash.
- **Nightshift**: the code path exists and is tested against a local mock OpenAI-compatible server. It has not run against a real Nightshift endpoint from this box.
- **Zetaris JDBC**: tested with a fake JDBC connection that runs the rendered SQL on DuckDB. It has not run against a live Zetaris instance; see `docs/RUN_WINDOWS.md`.
- **Deadline scope**: the deadline is process-global (`llm._DEADLINE`). Two concurrent runs in one API process share it, so the later run's deadline wins. The demo runs one at a time.
- **Cost**: tokens come from the provider's `usage` field. On the NVIDIA free endpoint and the sample provider, cost is reported as 0 EUR. No list price is invented unless you pass `MODEL_PRICE_EUR_PER_MTOK`.

## Markovian control (bench harness only)
| Decision | Code | Log | Test |
|---|---|---|---|
| route EVIDENCE / NUMERIC (+DEEP) | `bench/markov.py` `Controller.route`, `reason_kind` | `decisions[]` in bench JSONL rows | `tests/test_markov_control.py` |
| gate retry/stop (expected gain) | `Controller.gate_retry` | same | same |
| SQL repair / give up | `Controller.sql_repair` | same | same |
| requery early stop | `Controller.requery` | same | same |
| rewrite vs drop (skip LLM call) | `Controller.rewrite` | same | same |
| depth from NVIDIA classifier | `Controller.insight_rounds`, `bench/features/nvclf-*.json` | same | same |
| reranker evidence/citation check | `Controller.evidence_check`, `bench/nv_rerank.py` | same, with `rerank_p` | same (offline) |
Gap: `app/pipeline.py` does not use the controller yet.
