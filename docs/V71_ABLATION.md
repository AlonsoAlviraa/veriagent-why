# V7.1 ablation — isolated pieces (DEVELOPMENT, design slice only)

Development after the pre-registered V7 run; does not change the 65.8% result. Code: `bench/v71x.py` (arms selected by system name, `V71=1`).

## Leakage check (Code Reviewer, first)
No target leakage found. V7.1 / every arm reads only `it.id`, `q.question`, `doc.table`, `doc.paragraphs`; answer type is the model's prediction or the regex detector. `tests/test_v71x.py::test_no_gold_leakage` deletes `q.answer/answer_type/scale/derivation/answer_from` and `doc.questions` and requires byte-identical output and prompts (wall-clock stamps excepted) for all 10 arms + `agent_mk71` × 3 question shapes: 33/33 pass.

## Slices
- Design: TAT-QA dev, seed-2026 order positions 420..719, n=300, sha256 `64bfa65c94147dfb…` (`docs/v71/design300.json`). Disjoint from 0..419, test500, pilot/hold-out manifests, test_gold.
- Hold-out: positions 720..1019, n=300, sha256 `5a8c7544ae39cc08…` (`docs/v71/holdout300.json`). **Not run, not inspected.**
- Nebius, `NEBIUS_STRICT=1`, nvidia/Nemotron-3_5-Lightning, T=0, 8 parallel shards, paired, no cache. Nothing tuned on this slice.

## Results (n=300 paired; EM/F1/sem in %; Δ EM vs V7 with bootstrap 95% CI, exact McNemar)
| arm | pieces | EM | F1 | sem | cov | fixed/broken vs V7 | ΔEM [CI] | p | Δsem |
|---|---|---|---|---|---|---|---|---|---|
| V7 (agent_mk) | — | 67.33 | 73.09 | 80.00 | 100 | — | — | — | — |
| f1 | structured output+scale | 56.00 | 61.55 | 64.67 | 88.7 | 8/42 | −11.33 [−16.0, −7.0] | <0.001 | −15.33 |
| f2 | extractive span | 68.00 | 73.74 | 80.00 | 100 | 6/4 | +0.67 [−1.33, +2.67] | 0.75 | 0.00 |
| g5a | gate sign | 66.33 | 72.12 | 78.67 | 100 | 1/4 | −1.00 [−2.67, +0.33] | 0.38 | −1.33 |
| g5b | gate empty/no-evidence | 67.33 | 72.54 | 80.67 | 100 | 3/3 | 0.00 [−1.67, +1.67] | 1 | +0.67 |
| g5c | gate length/list/scale | 66.67 | 72.20 | 78.67 | 99.7 | 4/6 | −0.67 [−2.67, +1.33] | 0.75 | −1.33 |
| base | V7+g5a+g5b | 67.33 | 72.85 | 80.67 | 99.7 | 5/5 | 0.00 [−2.0, +2.0] | 1 | +0.67 |

Code Reviewer ideas, each on base (acceptance: ΔEM vs base > 0 AND broken ≤ fixed/3):
| idea | EM | fixed/broken vs base | ΔEM vs base [CI] | p | accepted |
|---|---|---|---|---|---|
| A trim to sub-span | 67.67 | 6/5 | +0.33 [−1.67, +2.33] | 1 | no (5 > 2) |
| B type detector / year-from-header | 68.67 | 8/4 | +1.33 [−1.0, +3.67] | 0.39 | no (4 > 2.67) |
| C scale only if literal | 49.33 | 10/64 | −18.0 [−23.3, −13.0] | <0.001 | no |
| D keep lists | 67.00 | 3/4 | −0.33 [−2.0, +1.33] | 1 | no |

**No idea accepted → combined config = V7 unchanged** (`docs/v71/combined_config.json`, with its sha256). The hold-out was not run; it is waiting for Code Reviewer to review the diff.

Detector confusion on design (gold type → predicted): arithmetic 119/120 correct; count 6/8; span 75/120 (27→arithmetic, 11→year); multi-span only 13/52 → list.

## Reading
- The −10 pp of V7.1 comes almost entirely from **f1 (the structured writer prompt)**: −11.3 pp, 42 broken, coverage drops to 88.7% (empty/invalid `value`).
- **C** (scale only if literal) is strongly harmful: TAT-QA gold scale is often set by table headers like "$m"/implicit units for lookups too.
- f2 and B are the only positive ones, both small and not significant; B fails the break-ratio rule.
- g5a/g5b/g5c are neutral to slightly negative on EM.

## Recommendations
1. Drop f1 and C. Keep V7's prompt and its scale post-step.
2. f2 and B are candidates for a larger design slice (n ≥ 600 needed to resolve a +1 pp effect) — not for the hold-out yet.
3. g5b is worth keeping as an audit-only guard (0 EM cost, closes c3ef3efb4a4e) if Alonso wants the abstention behaviour; g5a as implemented costs 4 items and should be revised before reuse.
4. Do not run the hold-out until a candidate meets the rule on design.

## Test battery (`tests/test_v71x.py`, + existing `tests/test_v71.py`)
Full suite in a clean env: 279 passed, 3 skipped, 49 xfailed. New file: 98 passed / 49 xfailed:
leakage invariant (33), A substring/idempotence (9), detector 5 types × 30 synthetic template questions (5), scale-literal (1), list cardinality / no-collapse / text not split (7), gate g5b empty/no-evidence abstain, g5a 1046abe8 shape (no wrong sign flip on a 'change' question) and negative 'difference' flagged (3).
Diagnostic fixtures from eval400 (`tests/fixtures/v71_diag_eval400.json`, never used to accept ideas): deterministic layers A+B+D recover 18/64 regressions (46 xfail with reason) and preserve 21/24 fixes (3 xfail).
Note: 3 pre-existing tests fail only when live-run env vars (LLM_CACHE=0, LLM_PROVIDER, …) are exported; they pass in a clean env.

Cost: ledger 6.119 → 6.716 USD (≈ $0.60 for 3,300 rows), cap 15.
