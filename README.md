# VeriAgent Why

**Open Agent Hackathon 2026 · Track: The Agent That Can Explain Why (Track 02)**

> **Status: skeleton.** The build window opened on 22 Oct 2026 at 02:00 Madrid time (00:00 UTC). This first commit contains only the declared pre-existing skeleton and design documents; all implementation code is written in Cursor during the build window.

VeriAgent Why is a multi-agent system for e-commerce ops/finance analysts that investigates "why did this KPI change?" questions (on-time delivery rate, return rate) over federated data (Zetaris), tests competing hypotheses against evidence, and returns a decision memo where every claim cites source rows, with a deterministic confidence score and explicit limitations.

## Architecture
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/diagrams/veriagent_why_arch_v6.2.png`](docs/diagrams/veriagent_why_arch_v6.2.png).

Main flow: Planner → Retriever (Zetaris SQL + BM25) → S1 Relevance Filter → Evidence Evaluator (requery loop to the Planner, max 3) → Cause Analyst → Writer → deterministic Claim Gate (loop to the Cause Analyst, max 2) → decision memo. Meterless H-MEM holds the hypothesis/evidence graph; Meterless Markovian handles long investigations.

## Setup
```bash
git clone https://github.com/AlonsoAlviraa/veriagent-why
cd veriagent-why
cp .env.example .env   # fill in your own values locally
```
## Run (SAMPLE_MODE, offline, no credentials)
```bash
make setup          # venv + requirements
make run            # one demo investigation (SAMPLE_MODE)
make test           # pytest
make api            # API on :8000 (POST /run, POST /runs, GET /runs/{id}/trace, /memo/{id}.md|.pdf)
make ui             # web UI on :8501 (separate port; only calls the API)
make data eval-dev  # build eval datasets, run the dev split
make scan clean-check
docker compose up --build   # api :8000 + ui :8501
```
`SAMPLE_MODE` defaults to `true` when unset: no model calls, real SQL over the synthetic views, Meterless engines via `node`. Each run writes `logs/trace-<run_id>.jsonl`, `logs/hmem-ledger-<run_id>.jsonl`, `logs/memo-<run_id>.md` and `.pdf`.

UI: question and KPI, live trace of rounds (including Evaluator send-backs), H-MEM evidence graph (supports/refutes edges), memo with clickable row-ID citations, confidence breakdown (C, A, R, caps, per-view agreement), PDF/Markdown export, and a what-if that is always labelled ESTIMATE.

## Current status (22 Oct 2026)
- Working in SAMPLE_MODE: KPIs `on_time_rate` and `return_rate`; hypothesis families carrier/region segments (with drill-down), promotion, and seasonality (broad rise); promotion-vs-carrier cross-view check; materiality guard; Claim Gate; deterministic confidence; Meterless H-MEM + Markovian; API, UI, PDF; eval harness; CI.
- Implemented but untested against real services: LLM calls (tested only with a mock OpenAI-compatible server), Zetaris REST backend (tested only with a mock of the documented REST shape).
- Not yet: live Nemotron/Nightshift runs, a live Zetaris instance with the synthetic views loaded, model-based eval.

## Meterless engines (how they are used)
The open-source Meterless reference engines (github.com/Meterless/Meterless, Apache-2.0, pinned commit in `vendor/meterless/README.md`) are vendored unmodified and called through `meterless_bridge/` (a JSON-lines bridge run with `node`; prebuilt bundle committed, so SAMPLE_MODE needs no `npm install`).
- **H-MEM** stores the evidence graph: every hypothesis, evidence node and support/refute edge is an H-MEM record (edges carry `derivedFrom=[evidence, hypothesis]`). The H-MEM trust ledger is exported per run to `logs/hmem-ledger-<run_id>.jsonl`. The Planner recalls H-MEM context when it plans.
- **Markovian** drives the Evaluator → Planner rounds: each investigation round is one Markovian chunk, the round summary is the `[STATE_CHECKPOINT]` carryover, and `[TASK_COMPLETE]` ends the loop (max 3 chunks). Its run record (chunks, carryover, estimated tokens) is in the run output and trace.
- If `node` is missing the pipeline falls back to a local in-process graph and says so in the trace and memo.

## Model providers
`LLM_PROVIDER=nightshift|nvidia|sample` (`SAMPLE_MODE=true` forces `sample`). `nightshift`: Meterless Nightshift OpenAI-compatible endpoint (`NIGHTSHIFT_BASE_URL`). `nvidia`: NVIDIA API (`NVIDIA_API_KEY`, read from the environment only, never logged). Models: `REASONING_MODEL` (default `nvidia/nemotron-3.5-super-vl-120b-a12b`, S2: Planner, Cause Analyst, Writer) and `FAST_MODEL` (default `nvidia/nemotron-3.5-lightning-30b-a3b`, S1: relevance filter, Evaluator). Model outputs are validated JSON; any failure (empty reply, HTTP error, invalid JSON or label) falls back to the deterministic path and is logged. Numbers always come from SQL.

## Evaluation
`make data`, `make eval-dev`, `make eval-test` (frozen; hash in `eval/SPLITS.sha256`).
28 questions on seeded synthetic datasets: 10 dev (4 added later, see below), 18 test. Negative controls in both splits; the demo scenario in neither. Baseline: plain RAG (BM25 over serialised rows, same data, question and token budget; same model in live mode). Metric: exact match of `top_cause_label`, k/n with a Wilson 95% interval.
History and caveats: [`eval/RESULTS_HISTORY.md`](eval/RESULTS_HISTORY.md). In short, with the sample provider (no model on either side): test run 1, 14/18 vs 6/18; after adding seasonality and promotion-vs-carrier logic tuned on 4 new dev questions, test run 2, 18/18 vs 6/18. Run 2 is not an unseen-family evaluation, and the data is clean synthetic data written by the same author. The model-based comparison has not been run.

## Confidence (deterministic)
`conf = round(100 × (0.45·C + 0.35·A + 0.20·(1−R)))`, where C = share of all proposed claims that passed the Claim Gate, A = share of views with relevant rows that agree with the top cause (A = 0 and cap 50 if none), R = refuting ÷ (supporting + refuting) edges for the top cause. Partial runs are capped at 40. See `app/confidence.py`.

## AI and Model Usage
Models (product runtime):
- NVIDIA Nemotron via the provider switch: `nvidia/nemotron-3.5-super-vl-120b-a12b` (S2: Planner, Cause Analyst, Writer) and `nvidia/nemotron-3.5-lightning-30b-a3b` (S1: relevance filter, Evidence Evaluator). **Status: wired and tested only against a mock server; no real model call has been made yet.**
- Meterless Nightshift as the primary provider (`LLM_PROVIDER=nightshift`, OpenAI-compatible, `meterless/*` routing modes). **Status: not available yet** (no runtime reachable); `nvidia` is the direct fallback, disclosed per call in the trace.
- SAMPLE_MODE uses no model at all: deterministic rules with real computation.
- Model output never supplies numbers or confidence: numbers come from SQL, confidence from a formula, and the Claim Gate checks every number in model-written text.

Agent framework: none; own Python orchestrator (`app/pipeline.py`).

Sponsor technology:
- Zetaris: data layer behind `app/adapters/zetaris.py` (REST backend implemented from the public setup guide, untested live; SAMPLE_MODE uses a DuckDB snapshot with the same five view names and SQL).
- Meterless: H-MEM (evidence graph + trust ledger) and Markovian (investigation rounds) open-source reference engines, vendored unmodified (Apache-2.0) and run through `meterless_bridge/`; Nightshift as the model provider (pending).
- NVIDIA: Nemotron models above (pending live use).
- Cursor: development environment.

Development tools: developed in Cursor; AI-assisted coding was used for scaffolding, implementation, tests and documentation. Generated code was reviewed and tested by the author.

External libraries: DuckDB, FastAPI, Uvicorn, httpx, fpdf2, pytest; esbuild (build-time only, for the bridge bundle); Meterless engines (vendored).
Data: synthetic, generated by `scripts/make_data.py` (seeded); no real customer data.
Open-source code materially adapted: Meterless reference engines (vendored unmodified, see `vendor/meterless/README.md`).

## Pre-existing work
Everything below was prepared before the build window opened and is also declared in the submission form. Full detail: [`docs/PRE_EXISTING_WORK.md`](docs/PRE_EXISTING_WORK.md).

1. **Environment setup only (no product code):** local Zetaris hackathon platform, Zetaris account and API key; NVIDIA API key with Nemotron availability tests.
2. **Throwaway connectivity scaffold** ("open-agent-hack"): smoke tests and minimal wrappers for Zetaris, Nemotron and Meterless. Not the submitted codebase and not included here.
3. **Meterless:** the public open-source Meterless starter installed locally, plus a small bridge, Python client and JSONL audit logger used in a connectivity test. Not included here.
4. **Design material:** all architecture diagrams for VeriAgent Why, versions v2 through v6.2 (including v5A/B/C, v6, v6.1, data-layer v2/v3), the Python scripts used to generate them, the author's earlier architecture sketches (S1/S2 fast-filter pattern), the architecture documents (including `docs/ARCHITECTURE.md`, from ARCH_V6.1) and a summary of the official hackathon resources.
5. **This repository skeleton:** folder structure, templates (README, metadata, `.env.example`), example input/output stubs, and docs outlines (agent loop spec, I/O contract, deck outline, demo script, sponsor tech). TODOs only, no implementation code.
6. **Concept origin:** the author's earlier personal project [VeriAgent](https://github.com/AlonsoAlviraa/VeriAgent). No code copied; only the "verify before you answer" idea and the name are reused.

Pre-existing open-source libraries are used under their own licences, including the Meterless H-MEM and Markovian reference engines (vendored, Apache-2.0). The earlier connectivity bridge from item 3 is not reused; `meterless_bridge/` was written during the build window.

## License
MIT. See [LICENSE](LICENSE).

## Team
Alonso Alvira Ballano (solo). GitHub: [@AlonsoAlviraa](https://github.com/AlonsoAlviraa)
