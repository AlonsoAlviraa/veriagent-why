# VeriAgent Why

**Open Agent Hackathon 2026 · Track: The Agent That Can Explain Why (Track 02)**

> **Status: skeleton.** The build window opened on 22 Oct 2026 at 02:00 Madrid time (00:00 UTC). This first commit contains only the declared pre-existing skeleton and design documents; all implementation code is written in Cursor during the build window.

VeriAgent Why is a multi-agent system that investigates "why did this metric change?" questions over federated data (Zetaris), tests competing hypotheses against evidence, and returns a decision memo where every claim cites source rows, with a deterministic confidence score and explicit limitations.

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
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/make_data.py            # builds data/snapshot.duckdb (synthetic, seeded); also built on demand
python run.py --input input_examples/example_1.json
python -m pytest -q
python run.py --serve                  # POST http://localhost:8000/run
```
`SAMPLE_MODE` defaults to `true` when unset. In sample mode the agents use their deterministic path (no language model), with real SQL over the synthetic views. Each run writes `logs/trace-<run_id>.jsonl` and `logs/memo-<run_id>.md`. `output_examples/example_1.json` is the saved output of the command above.

## Current status (build day 1)
- Working: seeded synthetic data generator, full agent pipeline in SAMPLE_MODE with both loops, deterministic Claim Gate and confidence, JSONL traces, Markdown memo, FastAPI `POST /run`, tests.
- Not yet: Zetaris backend (the adapter has a sample DuckDB backend; the Zetaris REST backend is a TODO), Meterless H-MEM / Markovian (a local in-process stand-in with the same role is used for now), live Nemotron calls through Nightshift or NVIDIA (provider switch wired, not used by agents yet), eval harness and baseline, UI, PDF memo.

## Confidence (deterministic)
`conf = round(100 × (0.45·C + 0.35·A + 0.20·(1−R)))`, where C = share of all proposed claims that passed the Claim Gate, A = share of views with relevant rows that agree with the top cause (A = 0 and cap 50 if none), R = refuting ÷ (supporting + refuting) edges for the top cause. Partial runs are capped at 40. See `app/confidence.py`.

## AI and Model Usage
Placeholder, to be completed as the build progresses.
- **Cursor:** development environment; AI-assisted coding, reviewed and tested by the author.
- **NVIDIA Nemotron:** planned reasoning and fast-filter models via the NVIDIA API (exact model IDs TBD).
- **Meterless:** Nightshift as the primary OpenAI-compatible model provider, plus the H-MEM, Markovian and World Model engines (JSONL traces).
- **Zetaris:** federated data layer queried for evidence.
- Data: synthetic, clearly labelled sample data (to be added).

## Pre-existing work
Everything below was prepared before the build window opened and is also declared in the submission form. Full detail: [`docs/PRE_EXISTING_WORK.md`](docs/PRE_EXISTING_WORK.md).

1. **Environment setup only (no product code):** local Zetaris hackathon platform, Zetaris account and API key; NVIDIA API key with Nemotron availability tests.
2. **Throwaway connectivity scaffold** ("open-agent-hack"): smoke tests and minimal wrappers for Zetaris, Nemotron and Meterless. Not the submitted codebase and not included here.
3. **Meterless:** the public open-source Meterless starter installed locally, plus a small bridge, Python client and JSONL audit logger used in a connectivity test. Not included here.
4. **Design material:** all architecture diagrams for VeriAgent Why, versions v2 through v6.2 (including v5A/B/C, v6, v6.1, data-layer v2/v3), the Python scripts used to generate them, the author's earlier architecture sketches (S1/S2 fast-filter pattern), the architecture documents (including `docs/ARCHITECTURE.md`, from ARCH_V6.1) and a summary of the official hackathon resources.
5. **This repository skeleton:** folder structure, templates (README, metadata, `.env.example`), example input/output stubs, and docs outlines (agent loop spec, I/O contract, deck outline, demo script, sponsor tech). TODOs only, no implementation code.
6. **Concept origin:** the author's earlier personal project [VeriAgent](https://github.com/AlonsoAlviraa/VeriAgent). No code copied; only the "verify before you answer" idea and the name are reused.

Pre-existing open-source libraries are used under their own licences.

## License
MIT. See [LICENSE](LICENSE).

## Team
Alonso Alvira Ballano (solo). GitHub: [@AlonsoAlviraa](https://github.com/AlonsoAlviraa)
