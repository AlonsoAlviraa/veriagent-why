# Pre-existing work: VeriAgent Why (Open Agent Hackathon 2026)

> Everything below was prepared **before the build window opened (22 Oct 2026, 00:00 UTC)**. It is declared here and in the submission form's "pre-existing components" field. Dates verified against file timestamps on the dev PC on 19 Oct 2026 (Zetaris platform images pulled from 12 Oct; all scaffold, Meterless and diagram files dated 15 Oct 2026, 19:45–23:18 Madrid time).

## Ready to paste into the submission form

```
Pre-existing components (all prepared before 22 Oct 2026 00:00 UTC):

1. Environment setup only (no product code): local Zetaris hackathon platform installed via the official zetaris-platform Docker setup (verify.sh 9/9), a Zetaris Cloud Hobby account and a Zetaris API key (15 Oct 2026); an NVIDIA build.nvidia.com API key, with Nemotron model availability tested (15 Oct 2026).

2. A throwaway connectivity scaffold, "open-agent-hack" (15 Oct 2026): a smoke test (Zetaris web, Zetaris SQL, Nemotron, Meterless) and minimal wrappers (agent/llm.py, agent/tools_zetaris.py, agent/main.py). It is NOT the submitted codebase; the submission repo was started from an empty skeleton during the build window. Any idea reused from it is re-implemented and noted in the README.

3. Meterless: the public open-source Meterless starter (github.com/Meterless/Meterless) installed locally, plus a small Node bridge (bridge.ts), a Python client (meterless.py) and a JSONL audit logger used in an end-to-end connectivity test (15 Oct 2026). Meterless itself is a pre-existing open-source library.

4. Design material (design only, no product code), all made before 22 Oct 2026 00:00 UTC: architecture diagrams for VeriAgent Why v2, v3, v4 (+ data-layer v2/v3) (15 Oct 2026) and v5A, v5B, v5C, v6, v6.1, v6.2 (20–21 Oct 2026); the Python scripts that generate them (gen.py, gen_v3.py, gen_v4.py, gen_v5.py, gen_v5abc.py, gen_v6.py, gen_v6_1.py, gen_v6_2.py); the author's earlier hand-drawn architecture sketches (arq1, arq2: the System-1/System-2 fast-filter pattern) and architecture-ata.svg; a relevance-judge concept from an earlier personal design sketch (concept only); the architecture documents (ARCH_V5_OPTIONS, ARCH_V6, ARCH_V6.1, included here as docs/ARCHITECTURE.md); and a written summary of the official hackathon resources (15 Oct 2026).

5. Repository skeleton (19 Oct 2026): empty folder structure with README/metadata/.env.example templates, a deck outline and a demo script outline, containing TODOs only and no implementation code.

6. Concept origin: the author's earlier personal project VeriAgent (github.com/AlonsoAlviraa/VeriAgent, Dec 2025–Aug 2026), a multi-agent fiscal-compliance system for Spanish VeriFactu. No code from it is copied into this submission unless explicitly listed in the README; only the general "verify before you answer" idea (re-implemented, not copied) and the name are reused.

Everything else (agents, adapters, Zetaris data model, Meterless H-MEM/Markovian integration, logs, samples, UI, Docker, deck and video) was built in Cursor during the build window.
```

## Detail and evidence

| # | Item | Location on dev PC | Date | Notes |
|---|---|---|---|---|
| 1 | Zetaris local platform (`verify.sh` 9/9; UI :3000, REST :8888) | `Hackaton\zetaris-platform` | 15 Oct 2026 | Official hackathon images (zetarishackathon.azurecr.io) |
| 2 | Zetaris getting-started repo | `Hackaton\zetaris-getting-started` | 15 Oct 2026 | Official sponsor material, unmodified |
| 3 | Zetaris API key "open-agent-hack" | (secret, in .env only) | 15 Oct 2026 | Expires ≈12 Jan 2027 |
| 4 | NVIDIA API key and model tests (rerank-vl-1b-v2, nemotron-3.5-lightning-30b-a3b, nemotron-3.5-super-vl-120b-a12b, nemotron-3-embed-1b, content-safety) | `ARQUITECTURA\nvidia_models.md` | 15 Oct 2026 | Availability check only |
| 5 | `open-agent-hack` scaffold: `smoke_test.py`, `agent/llm.py`, `agent/tools_zetaris.py`, `agent/main.py`, `prompts/`, `.env`, `.gitignore` | `Hackaton\open-agent-hack` | 15 Oct 2026 | Connectivity tests; smoke test 4/4 PASS |
| 6 | Meterless starter + `bridge.ts` + `meterless.py` + JSONL audit (`logs\audit.jsonl`) | `Hackaton\meterless-starter`, `open-agent-hack` | 15 Oct 2026 | End-to-end test: H-MEM recall → Markovian plan → Zetaris query → 4 audited steps |
| 7 | Architecture diagrams v2, v3, v4 (+ data-layer v2/v3); v5A/B/C, v6, v6.1, v6.2; generator scripts `gen*.py`; sketches arq1/arq2, architecture-ata.svg; architecture docs | `Hackaton\ARQUITECTURA` and the author's working folder | 15–21 Oct 2026 | Design only |
| 8 | Resources summary | `Hackaton\RESOURCES_SUMMARY.md` | 15 Oct 2026 | Notes on the official docs |
| 9 | Repo skeleton `veriagent-why` (TODO stubs) | `Hackaton\veriagent-why` | 19 Oct 2026 | No implementation code |
| 10 | VeriAgent (personal project) | github.com/AlonsoAlviraa/VeriAgent | 29 Dec 2025 – 13 Aug 2026 | Prior project; concept origin only |

Rule reference: "Work committed before the build window opens is not eligible, except for clearly declared pre-existing components. Pre-existing open-source libraries are permitted. Pre-existing product code must be declared in the submission form." (Official Rules §8.2)
