# VeriAgent Why

**Open Agent Hackathon 2026 · Track 02: The Agent That Can Explain Why**

> **Status: skeleton.** The build window opened on 22 Oct 2026 at 02:00 Madrid time (00:00 UTC). This first commit contains only the declared pre-existing skeleton and design documents; all implementation code is written in Cursor during the build window.

VeriAgent Why is a multi-agent system that investigates "why did this metric change?" questions over federated data (Zetaris), tests competing hypotheses against evidence, and returns a decision memo where every claim cites source rows, with a deterministic confidence score and explicit limitations.

## Architecture
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/diagrams/veriagent_why_arch_v6.2.png`](docs/diagrams/veriagent_why_arch_v6.2.png).

Main flow: Planner → fast relevance filter → Evidence Evaluator (requery loop) → Cause Analyst → Writer → deterministic Claim Gate → Memo. Meterless H-MEM holds the hypothesis/evidence graph; Meterless Markovian handles long investigations.

## Setup
```bash
git clone https://github.com/AlonsoAlviraa/veriagent-why
cd veriagent-why
cp .env.example .env   # fill in your own values locally
```
`SAMPLE_MODE=true` is planned to run offline with no credentials. Not implemented yet.

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
4. **Design material:** all architecture diagrams for VeriAgent Why, versions v2 through v6.2 (including v5A/B/C, v6, v6.1, data-layer v2/v3), the Python scripts used to generate them, the architecture documents (including `docs/ARCHITECTURE.md`, from ARCH_V6.1) and a summary of the official hackathon resources.
5. **This repository skeleton:** folder structure, templates (README, metadata, `.env.example`), example input/output stubs, and docs outlines (agent loop spec, I/O contract, deck outline, demo script, sponsor tech). TODOs only, no implementation code.
6. **Concept origin:** the author's earlier personal project [VeriAgent](https://github.com/AlonsoAlviraa/VeriAgent). No code copied; only the "verify before you answer" idea and the name are reused.

Pre-existing open-source libraries are used under their own licences.

## License
MIT. See [LICENSE](LICENSE).

## Team
Alonso Alvira Ballano (solo). GitHub: [@AlonsoAlviraa](https://github.com/AlonsoAlviraa)
