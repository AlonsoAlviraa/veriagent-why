# Evaluation

| Set | File | Questions | Status |
|---|---|---|---|
| dev | `questions.json` (split `dev`) | 18 | Used for tuning. Grows over time (clean cases first, then 4 trap-family cases, then 8 noisy cases). |
| test v1 | `questions.json` (split `test`), hash `SPLITS.sha256` | 18 | **Contaminated.** Run twice with the sample provider; the second run came after seeing the first run's failures. Kept only as history in `RESULTS_HISTORY.md`. Do not quote it as a held-out result. |
| test v2 | `questions_test_v2.json`, hash `SPLITS_test_v2.sha256` | 18 | **Held out, reserved for the final Nemotron eval.** Written before the robustness tuning, new seeds (5001+), noisy generator. Never run so far. `eval.py` refuses to run it without `--final-v2` and a live model provider. |

## Generator
`scripts/make_data.py`, seeded and deterministic. Every scenario plants its causes explicitly; `expected_label` (and, where defined, `expected_segment` / `expected_secondary`) is the planted truth. Agents never read these files.
Noisy variant (`noise` key, see `N()` in `make_questions.py`): per-carrier base late rates (4–10%), ±30% daily variance, ±15 orders/day volume noise, partial tickets/returns (30–70% of rows dropped), always-bad distractor segments, small period-only distractor bumps, and a second smaller planted cause (multi-cause).

## test_v2 composition
3 noisy carrier breaches, 3 multi-cause (primary + secondary breach), 2 noisy breaches with a date-matching promotion trap, 3 noisy promotion effects, 3 noisy seasonality, 4 negative controls (static distractor, small bump, heavy partial data, promotion without effect).

## Metric and protocol
- Primary: exact match of `top_cause_label`. Reported as k/n with a Wilson 95% interval, never as "significant".
- Secondary (where defined): segment match for the primary cause, secondary-cause detection.
- Baseline: plain RAG (`baseline_rag.py`): same data, question, token budget and model.
- Final protocol: one run of both systems on test_v2 with the same Nemotron provider, logged with commit hash, provider and model IDs in `RESULTS_HISTORY.md`, whatever the result.

## Commands
`python eval/make_questions.py`, `python eval/make_test_v2.py` (already run; do not regenerate), `python eval/build_datasets.py [--v2]`, `python eval/eval.py --split dev`, `python eval/eval.py --split test_v2 --final-v2` (final run only).
