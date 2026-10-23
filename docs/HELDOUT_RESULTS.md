# Held-out results (DRAFT, not yet run to completion)

Status: **superseded**. The final evaluation is `tatqa_test500_v1` (see PREREG.md). holdout_v1 became a pilot: partial runs, no 3-repeat rerun, not evidence.

## Protocol
- Candidate split: `bench/splits/holdout_v1.json`.
  - 100 ids drawn from the official TAT-QA `test_gold` file (sha256 `c4d08418…b597`).
  - Sampling: `random.Random(20261024)`.
  - ids_sha256: `2babf48b465dbaf66a7f4cd37b10b6dfaf39eb9b24db7b49a2ba0c5a0f6e5cab`.
  - Committed in 2c25dac before any run. Disjoint from dev and train, and from every earlier artifact.
- Arms:
  - `base-agent_mk` at 828cdb2 (#7);
  - `fix-agent_mk`, `fix-agent_cr` and `fix-react` at fe698d2 (clean tree);
  - all on NVIDIA free, T=0, 3 repeats.
- Stats: `python -m bench.heldout_report bench/results/holdout --md`.
  - Per-item majority vote and exact McNemar.
  - Paired bootstrap 95% CI.
  - Mean ± sd over repeats.
  - Brier, ECE, AUROC and AURC on shipped (raw) confidence. The train-fitted map is reported descriptively only, and nothing is fit on held-out.
- InsightBench has no untouched tasks and is reported only as a "contaminated eval".

## Disclosures
- A partial run already touched all 100 candidate ids before the hold. It stopped at 23:57 Madrid time on 2026-10-23. The exact ids are in `bench/results/holdout/HOLD_MANIFEST.json`.
- Before the hold, about 9 fix-agent_mk outputs were inspected as a pipeline sanity check. No code or config changed as a result.

## Results
_TBD after the split decision._

## Defensible claims
_TBD. Only paired held-out differences whose CI excludes 0 will be claimed._
