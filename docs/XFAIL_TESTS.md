# Why the suite reports 49 xfailed tests

`make test` ends with `... passed, ... skipped, 49 xfailed`. All 49 are in one file, `tests/test_v71x.py`, and all are **diagnostic fixtures, not hidden failures of the shipped pipeline**. They are recorded wrong answers that the current code does not fix; they are kept visible on purpose instead of being deleted.

| Group | Test | Count | What it is | Why it is expected to fail |
|---|---|---|---|---|
| A | `test_diag_regression_recovered_by_layers[...]` | 46 | One case per eval400 question where V7.1 answered worse than V7 (`tests/fixtures/v71_diag_eval400.json`, kind `regressed`). The test replays the recorded V7.1 answer through the deterministic post-layers A+B+D (span trim, list split, year-from-header). | The layers recover 18 of 64 regressions; the other 46 are not recoverable by deterministic rules today (they need a different model answer). Each xfail prints the answer it got. |
| B | `test_diag_fix_preserved_by_layers[...]` | 3 | Cases where V7.1 *fixed* a V7 error (kind `fixed`); the test checks that the layers do not undo the fix. | The layers break 3 of 24 fixes. This is a known cost of the layers, listed rather than hidden. |
| C | `test_detector_accuracy_per_type[list]` | 0 or 1 | Question-type detector recall on synthetic phrasings. | xfails only if `list` recall drops below 0.9 ("Which are ..." phrasing). Currently passes, so it is not one of the 49. |

Rules for these fixtures (from `docs/V71_ABLATION.md`): the eval400 fixtures are **never used to accept ideas**; they only show what the layers do and do not fix. A group A xfail that starts passing (XPASS) is a real improvement; a group B xfail is a real regression the layers cause on 3 recorded cases.

Nothing in the SAMPLE_MODE demo path (`run.py`, `app/pipeline.py`) depends on these tests.
