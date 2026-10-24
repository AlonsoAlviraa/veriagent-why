# TAT-QA test500: final pre-registered evaluation, agent_mk (NVIDIA) vs rag (Nebius)

Split `bench/splits/tatqa_test500_v1.json` (n=500, ids sha256 `02b8820dcc24918f…`). Pre-registration: `PREREG.md`;
frozen config `bench/freeze/test500_v1.json` (sha256 `50c2864f…c4c4`). All primary result rows carry code_rev `74591af`, dirty=false.
One run per arm, T=0. No code, prompt, threshold or config change was made after any result was seen.
Raw generated report: `docs/TEST500_REPORT_RAW.md`, `docs/test500_report.json` (includes the full risk-coverage curves).

**The primary comparison is cross-provider:** agent_mk ran entirely on NVIDIA's free endpoint, rag entirely on Nebius
(same model, Nemotron 3.5 Lightning; see deviation 1). This contradicts the frozen config, which named NVIDIA for both arms.
A post-hoc replica with both arms on Nebius is reported below; it was not part of the pre-registration.

## Results (primary, pre-registered)

| arm | provider | EM | F1 | calls/item |
|---|---|---|---|---|
| agent_mk (shipped) | NVIDIA | **0.658** | 0.745 | 2.45 |
| rag (reference) | Nebius | 0.528 | 0.605 | 1.00 |

Paired rag → agent_mk: agent_mk +0.130 EM, bootstrap 95% CI [+0.086, +0.174]; McNemar p < 0.001
(agent_mk right / rag wrong on 97 items, the reverse on 32).

Retry sensitivity: 13 agent_mk items needed a resume pass (deviation 3); 8 of those 13 ended correct (0.62, below the
0.658 base rate). Worst case, counting all 13 as wrong: agent_mk EM **0.642**, still **+0.114** over rag.

Pre-registered operating point (signal lex = conf_det + conf_raw/100, answer iff lex ≥ 0.809):

| arm | coverage | selective EM | AUROC (raw conf) | ECE |
|---|---|---|---|---|
| agent_mk | 0.842 (421/500) | 0.696 (vs 0.658 at full coverage) | 0.565 | 0.327 |
| rag | 0.000 (rag emits no deterministic confidence, so lex < 0.809 always) | n/a | **0.669** | 0.422 |

The lex AURCs (agent_mk 0.501, rag 0.526) are **not comparable**: rag has no conf_det, so its lex is not the same
signal. No AURC "win" is claimed. On the signal both arms do share, raw self-reported confidence, rag ranks its
answers better than agent_mk (AUROC 0.669 vs 0.565).

Caveats, stated plainly:
- The selective gain is modest (+3.8 pts EM for 15.8% abstention). The threshold was fit on dev rows from the trace-fix
  code (PREREG.md), a different system from the shipped agent_mk, which likely explains part of the weak gain.
  Raw self-reported confidence is poorly calibrated (mean 0.97 vs accuracy 0.66).
- lex takes only 8 distinct values for agent_mk. The curve code breaks ties pessimistically (wrong answers first within
  a tie), so the curve start (risk 1.0 at low coverage) and the AURC are worst-case artifacts of tie-breaking, not
  "top-confidence answers are all wrong". Per-tier accuracy: lex 0.81 → 237/325 (0.73); 0.809 → 56/96 (0.58);
  0.80 → 2/5; ~0.56 → 5/14; ~0.21 → 16/47; 0.11 → 13/13. This is the pre-registered metric definition; it was not changed.
- Single pre-registered run, single dataset, single model. Run-to-run variance comes only from the post-hoc replica below.

## Declared deviations and run log (all times Europe/Madrid, 2026-10-24)

1. **RAG provider changed after the freeze, and the switch was decided after the interim look.** The freeze specified
   NVIDIA's free endpoint for both arms. At 16:17, after the 15:38 interim look at partial agent_mk EM and with the
   agent_mk pass-1 outcome known, the owner asked to move the rag arm to Nebius for speed, only if it serves the same model.
   Verified first: NVIDIA `nvidia/nemotron-3.5-lightning-30b-a3b` and Nebius `nvidia/Nemotron-3_5-Lightning` are the same model
   (Nemotron 3.5 Lightning, 30B total / 3B active). Nebius serves bf16; NVIDIA's serving precision is not disclosed.
   T=0, same code, same prompts, NEBIUS_STRICT=1. agent_mk stayed entirely on NVIDIA. rag ran 16:19–16:33. Nothing was
   tuned (same code_rev), but the serving stack is a confounder of unknown sign; the replica below addresses it post hoc.
2. **Interim look at 15:38.** The partial agent_mk EM was viewed while the run was in progress. No code, prompt or config
   changed as a result; the provider switch in item 1 came after it.
3. **Failed agent_mk items.** After the first pass 13 of 500 agent_mk rows had errors (mostly HTTP 429 rate limits from the
   free endpoint; ~9 at the time of the 16:17 message, more accrued by the end of the pass). Per the pre-registered
   procedure (up to 3 resume passes, same command, same frozen commit/config; `bench.run` re-runs only items whose
   rows errored), pass 2 resolved 11 and pass 3 resolved the last 2. 0 errors remain. The report uses the
   non-error row for each item; errored attempts stay in the jsonl for audit. Sensitivity: see "Retry sensitivity" above.
4. **Script stop at 16:18.** To avoid double-launching rag on NVIDIA, the `bench_test500.sh` driver was stopped (SIGTERM) at
   16:18. The agent_mk worker kept running untouched and completed pass 1. Passes 2–3 and the report step were then run
   by hand with the exact same env and command as the script. rag (Nebius) ran in parallel: 500/500 in pass 1, 0 errors.
5. The run was never restarted from scratch and no completed item was rerun.

## Post-hoc replica: both arms on Nebius (not pre-registered)

Run after the primary result was known, at code_rev `bc0c8de` (dirty=false; the only changes since `74591af` are the
primary results docs under `docs/`, no code), same split, T=0, `--repeat 0`, NEBIUS_STRICT=1, model `nvidia/Nemotron-3_5-Lightning` for every role.
It was meant as one pass split over 8 shards, but the shard id filter was not applied, so **each of the 8 shards ran
all 500 items: 8 full replicates per arm** (4000 rows per arm). Rows that errored were resumed (up to 3 passes per
shard, same command); 0 errors remain. Raw report: `docs/TEST500_NEBIUS_REPORT_RAW.md`, `docs/test500_nebius_report.json`.
The lex threshold 0.809 was fit before any of this and on NVIDIA-era dev rows; it was applied unchanged.

| arm (Nebius) | EM per replicate | EM mean ± sd | EM majority of 8 | F1 mean | calls/item |
|---|---|---|---|---|---|
| agent_mk | 0.680, 0.676, 0.660, 0.674, 0.674, 0.676, 0.672, 0.666 | 0.672 ± 0.006 | 0.676 | 0.755 | 2.25 |
| rag | 0.518, 0.510, 0.514, 0.516, 0.510, 0.520, 0.520, 0.520 | 0.516 ± 0.004 | 0.520 | 0.597 | 1.00 |

- **Same provider, the gap holds and is slightly larger:** agent_mk − rag = +0.156 EM (per-item mean over 8 replicates),
  bootstrap 95% CI [+0.119, +0.194]; McNemar on the majority vectors p < 0.001 (95 vs 17 discordant). In every single
  replicate pair rk vs rk the gap is between +0.146 and +0.166, McNemar p ≤ 5e-12.
- **Agreement with the primary run:** rag on Nebius reproduces the primary rag closely (per-item EM agreement 0.970–0.986
  per replicate; majority 0.988; 0.528 primary vs 0.510–0.520 replica). agent_mk on Nebius vs agent_mk on NVIDIA:
  per-item agreement 0.904–0.914 (majority 0.918); primary 0.658 sits just below the replica range 0.660–0.680, and
  the paired difference (NVIDIA − Nebius majority) is −0.014, CI [−0.038, +0.010], McNemar p = 0.21. So the provider
  switch did not inflate the primary gap; if anything NVIDIA scored agent_mk slightly lower.
- **T=0 is not deterministic on either endpoint:** 39 agent_mk and 36 rag items change correctness across the 8 replicates.
- **Abstention at lex ≥ 0.809 (agent_mk):** coverage 0.803 pooled (0.792–0.816 per replicate), selective EM 0.711 pooled
  (0.699–0.721) vs 0.672 at full coverage, i.e. +3.9 pts, matching the primary's +3.8. rag again 0 coverage.
- **Confidence:** AUROC (raw conf) agent_mk 0.580 pooled (0.569–0.606 per replicate) vs rag 0.660; ECE agent_mk 0.313,
  rag 0.438. lex AURC 0.448 (agent_mk) vs 0.544 (rag) is again not comparable, for the same reason as above. The
  finding that rag's raw confidence ranks better than agent_mk's replicates.
- Cost: the whole replica stayed within the Nebius credit; the shared cumulative ledger read $6.00 at the end (≈ $4.93 before
  it; the ledger also counts any other process using Nebius at the same time), under the $15 stop and the $20 budget.

## Cost (primary)

agent_mk: $0 (NVIDIA free tier). rag on Nebius: ≈ $0.03 (Nebius ledger $4.899 → $4.933 cumulative; the delta is
mostly rag, plus any other process sharing the ledger). Cumulative ledger ≈ $4.93 at that point, well under the $15 stop and the $20 budget.
