# TAT-QA test500 — final pre-registered evaluation (results)

Split `bench/splits/tatqa_test500_v1.json` (n=500, ids sha256 `02b8820dcc24918f…`). Pre-registration: `PREREG.md`;
frozen config `bench/freeze/test500_v1.json` (sha256 `50c2864f…c4c4`). All result rows carry code_rev `74591af`, dirty=false.
One run per arm, T=0. No code, prompt, threshold or config change was made after any result was seen.
Raw generated report: `docs/TEST500_REPORT_RAW.md`, `docs/test500_report.json` (includes the full risk-coverage curves).

## Results

| arm | EM | F1 | calls/item |
|---|---|---|---|
| agent_mk (shipped) | **0.658** | 0.745 | 2.45 |
| rag (reference) | 0.528 | 0.605 | 1.00 |

Paired rag → agent_mk: agent_mk +0.130 EM, bootstrap 95% CI [+0.086, +0.174]; McNemar p < 0.001
(agent_mk right / rag wrong on 97 items, the reverse on 32).

Pre-registered operating point (signal lex = conf_det + conf_raw/100, answer iff lex ≥ 0.809):

| arm | coverage | selective EM | AURC (lex) | AUROC (raw conf) | ECE |
|---|---|---|---|---|---|
| agent_mk | 0.842 (421/500) | 0.696 (vs 0.658 at full coverage) | 0.501 | 0.565 | 0.327 |
| rag | 0.000 (rag emits no deterministic confidence, so lex < 0.809 always) | n/a | 0.526 | 0.669 | 0.422 |

Caveats, stated plainly:
- The selective gain is modest (+3.8 pts EM for 15.8% abstention). Raw self-reported confidence is poorly calibrated
  (mean 0.97 vs accuracy 0.66).
- lex takes only 8 distinct values for agent_mk. The curve code breaks ties pessimistically (wrong answers first within
  a tie), so the curve start (risk 1.0 at low coverage) and the AURC are worst-case artifacts of tie-breaking, not
  "top-confidence answers are all wrong". Per-tier accuracy: lex 0.81 → 237/325 (0.73); 0.809 → 56/96 (0.58);
  0.80 → 2/5; ~0.56 → 5/14; ~0.21 → 16/47; 0.11 → 13/13. This is the pre-registered metric definition; it was not changed.
- Single run, single dataset, single model; no repeats, so no run-to-run variance estimate.

## Declared deviations and run log (all times Europe/Madrid, 2026-10-24)

1. **RAG provider changed after the freeze.** The freeze specified NVIDIA's free endpoint for both arms. At 16:17 the
   owner asked to move the rag arm to Nebius for speed, only if it serves the same model. Verified first: NVIDIA
   `nvidia/nemotron-3.5-lightning-30b-a3b` and Nebius `nvidia/Nemotron-3_5-Lightning` are the same model
   (Nemotron 3.5 Lightning, 30B total / 3B active). Nebius serves bf16; NVIDIA's serving precision is not disclosed.
   T=0, same code, same prompts, NEBIUS_STRICT=1. agent_mk stayed entirely on NVIDIA.
2. **Interim look at 15:38.** The partial agent_mk EM was viewed while the run was in progress. Nothing was changed
   as a result.
3. **Failed agent_mk items.** After the first pass 13 of 500 agent_mk rows had errors (mostly HTTP 429 rate limits from the
   free endpoint; ~9 at the time of the 16:17 message, more accrued by the end of the pass). Per the pre-registered
   procedure (up to 3 resume passes, same command, same frozen commit/config; `bench.run` re-runs only items whose
   rows errored), pass 2 resolved 11 and pass 3 resolved the last 2. 0 errors remain. The report uses the
   non-error row for each item; errored attempts stay in the jsonl for audit.
4. **Script stop at 16:18.** To avoid double-launching rag on NVIDIA, the `bench_test500.sh` driver was stopped (SIGTERM) at
   16:18. The agent_mk worker kept running untouched and completed pass 1. Passes 2–3 and the report step were then run
   by hand with the exact same env and command as the script. rag (Nebius) ran in parallel: 500/500 in pass 1, 0 errors.
5. The run was never restarted from scratch and no completed item was rerun.

## Cost

agent_mk: $0 (NVIDIA free tier). rag on Nebius: ≈ $0.03 (Nebius ledger $4.899 → $4.933 cumulative; the delta is
mostly rag, plus any other process sharing the ledger). Cumulative ledger ≈ $4.93, well under the $15 stop and the $20 budget.
