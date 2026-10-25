# V9 round 1 — design slice only (n=600, 103 tables, TAT-QA train)

Pre-registration: `docs/V9_PREREG.md` (config hash `ee774546ef9ccf14`), committed before the run. Raw report:
`docs/v9/round1_report.json` (output of `python -m bench.v9_report`, unchanged). Rows (box only, not in repo):
`/workspace/v9-eval/r1_s{0..7}.jsonl`, sha256 prefixes f492c752 1d895fb1 800f906e b74b5ce2 786d3984 5a6f2601 f8c99c31 50288f8d.
600/600 items, 0 errors, logprobs returned on 100% of final calls, P(True) read from logprobs on 100%.
**Hold-out not opened.** Spend: ledger 7.2535 → 7.7512 (**+$0.50**, incl. a 2-item smoke and a probe).

## Answers (target unchanged: V7)
| system | EM | F1 (official) | semantic EM | calls/item | s/item | tokens/item |
|---|---|---|---|---|---|---|
| V7 | 63.67 | 71.11 | 77.33 | 2.22 | 3.0 | 2,046 |
| I3b (SC majority, V7 wins ties) | 63.50 | 71.07 | — | 6.23 | 7.6 | 5,998 |

I3b changed 10/600 answers: fixed 1, broken 2, ΔEM −0.17 (95% CI −0.83…+0.33), McNemar p=1.0 → **rejected** by the rule.
Self-consistency at T=0.7 with K=3 almost never disagrees with V7 — there is nothing to vote over. Negative, as expected from
PoT's note that SC helps less on financial data.

EM on train is **not comparable** to V7/V8 dev numbers (V7 dev-design 68.06, hold-out 64.67): different split, possible
pre-training exposure. All comparisons below are on the same 600 items.

## Confidence (target: V7 official EM; fitted scores out-of-fold, GroupKFold by table)
| score | extra calls over V7 | AUROC | ECE | Brier | AURC | sel. EM @ 84% cov |
|---|---|---|---|---|---|---|
| lex frozen (0.809) | 0 | 0.637 | 0.179 | 0.264 | 0.281 | 0.655 |
| lex Platt | 0 | 0.471 | 0.020 | 0.234 | 0.378 | 0.645 |
| I1 answer-token MSP (raw) | 0 | 0.698 | 0.155 | 0.224 | 0.255 | 0.708 |
| I2 P(True) (raw) | 1 | 0.639 | 0.324 | 0.352 | 0.261 | 0.681 |
| I2 verbalized (raw) | 1 | 0.613 | 0.328 | 0.334 | 0.268 | — (99.7% of items say ≥0.95) |
| I3 V7 share of 4 answers (raw) | 3 | 0.669 | 0.270 | 0.276 | 0.264 | 0.681 |
| **V8 refit** (pointer feats + lex) | 6.1 | 0.653 | 0.012 | 0.216 | 0.267 | 0.671 |
| **V9 cheap** (lex + I1 + I2) | 1 | **0.731** | 0.034 | 0.190 | 0.224 | 0.706 |
| **V9 full** (all + V8 feats) | 10.1 | **0.786** | 0.038 | 0.175 | 0.190 | 0.722 |

Pre-registered tests (bootstrap 95% CI of the difference, 2000 resamples):
* **H1 V9_cheap − lex_Platt: AUROC +0.199…+0.323 → passes**; ECE difference CI includes 0 → no calibration claim.
  **Caveat (found after the run, disclosed):** lex is almost constant (84% of items are 0.809/0.81, 19 distinct values), so
  out-of-fold Platt scrambles its ranking (AUROC 0.471 < 0.5). The comparison against lex_Platt is therefore too easy. Post-hoc,
  not pre-registered: V9_cheap − lex_frozen AUROC CI +0.044…+0.146 (still excludes 0); lex + I1 only (0 extra calls) AUROC 0.701,
  ECE 0.034, vs lex_frozen CI +0.010…+0.117.
* **H2 V9_full − V8_refit: AUROC +0.093…+0.173 → passes**; ECE CI includes 0.
* Secondary: V9_cheap − V8_refit AUROC +0.028…+0.130 (cheaper *and* better ranking, 1 vs 6 extra calls). Single raw signals vs
  lex_frozen: none has a CI excluding 0 (MSP closest: −0.002…+0.124). Raw P(True)/verbalized/SE are badly calibrated (ECE 0.27-0.33).
* No fitted score beats V8_refit or lex_Platt on ECE (all ~0.01-0.04); calibration is a tie, ranking is the gain.

## I4 conformal risk control (α = 0.10 for P(answered ∧ wrong), out-of-fold)
| score | realised risk | coverage | selective EM |
|---|---|---|---|
| lex Platt | 0.080 | 18.2% | 0.560 |
| V8 refit | 0.098 | 39.7% | 0.752 |
| V9 cheap | 0.095 | 46.8% | 0.797 |
| V9 full | 0.095 | 52.5% | 0.819 |
Risk is controlled at α in all arms; better ranking buys coverage at the same guarantee.

## Cost per item
V7 2.22 calls / 3.0 s / 2.0k tokens; V9 cheap 3.22 / 3.7 s / 2.7k (1.45x V7); V8 refit 8.32 / 8.6 s / 7.4k; V9 full 12.33 / 13.2 s / 11.3k (5.6x V7).
Design-run cost $0.50 total ($0.125 V9-cheap part).

## Honest limits
* One design slice, one model; train split (dev is burned). The H1 baseline was weak (see caveat). Hold-out will be the real test.
* ECE is computed on out-of-fold logistic scores; no isotonic step was pre-registered.
* The logistic combiner is fitted on 600 items/103 tables; feature weights not tuned (fixed l2 from V8).

## Proposal for the hold-out (needs Alonso's OK; recorded before opening it)
Run **V9_cheap** as the primary candidate (best value: AUROC gain at +1 call) and V9_full as secondary, both refitted on the full
design slice with the frozen code, one single run on `docs/v9/holdout.json` (n=400), est. cost ≈ $0.35 for V9_full items
(V9_cheap is a subset of the same calls). Primary hold-out test: V9_cheap vs **lex_frozen** and vs V8_refit, AUROC CI excluding 0.
