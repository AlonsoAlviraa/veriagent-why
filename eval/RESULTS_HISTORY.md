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
