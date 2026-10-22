# Eval results history (test split, frozen hash in eval/SPLITS.sha256)

All runs: provider `sample` (no language model on either side), seeded synthetic data, metric = exact match of `top_cause_label`, Wilson 95% CI. No significance claims.

| Run | Date (Madrid) | Code change before the run | VeriAgent Why | Plain-RAG baseline |
|---|---|---|---|---|
| 1 | 22 Oct 2026, morning | first test run | 14/18 (0.55–0.91) | 6/18 (0.16–0.56) |
| 2 | 22 Oct 2026, morning | seasonality hypothesis + promotion-vs-carrier cross-check, tuned on 4 new dev questions | 18/18 (0.82–1.00) | 6/18 (0.16–0.56) |

Caveats (read before quoting run 2):
- Run 2 is the one allowed rerun. After run 1 we knew which families failed (seasonality, promotion_effect). We added dev questions of those families and tuned only on dev, but the test items were seen in run 1's results, so run 2 is **not** an unseen-family evaluation.
- The data generator and the planted causes were written by the same author as the agent. The scenarios are clean and synthetic. Expect lower scores on real or noisier data.
- No model was used. The baseline's sample-mode reader is a fixed rule (`eval/baseline_rag.py`). The model comparison with Nemotron is still to be run.
- Details: `eval/history/`.

## Code changes after run 2 (test split NOT rerun; the rerun budget is used)
- KPI lens (`app/kpis.py`): `return_rate` added next to `on_time_rate`.
- Materiality guard in the Evidence Evaluator: no cause is supported if the KPI rose < 1 pp or by < 5 excess events; a promotion needs >= 5 excess events.
- Dev split after these changes (sample provider): agent 10/10, baseline 3/10, same as before. Test numbers above refer to the code at the run-2 commit.

## 22 Oct 2026, later: v1 test retired
The v1 test split is treated as **contaminated** from now on and will not be run again. A new held-out set, `questions_test_v2.json` (18 noisy questions, seeds 5001+), was written and frozen before the robustness work and is reserved for the final Nemotron eval. See `eval/README.md`.

## 22 Oct 2026, evening: first live Nemotron run (dev only)
Provider `nvidia` (free endpoint), 22 dev questions: agent 14/22 (0.43–0.80), baseline 11/22 (0.31–0.69); 570 agent model calls ok, 18 timed out (deterministic fallback), 3 baseline errors. Lower than sample mode (21/22); see `RESULTS_dev_nvidia.md` for the failure analysis. test_v2 not run.
