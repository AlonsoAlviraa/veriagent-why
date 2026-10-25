# V9.1 generalization results (frozen analysis, pre-registered in docs/V9_1_PREREG.md)

Sets: gen_secq (n_test=300), gen_jfinqa (305), gen_finqa (296). Each set was run once, with no errors and nothing missing. Label: semantic_correct (primary). Raw numbers: `docs/v9/gen/results.json`.

## Answer systems (semantic accuracy %)
| set | V7 agent | plain RAG |
|---|---|---|
| secq | 74.67 | 48.33 |
| jfinqa | 71.80 | 64.59 |
| finqa | 69.93 | 41.55 |

## Confidence signals: test AUROC (semantic label)
| arm | design OOF | oodsec (ref) | secq | jfinqa | finqa | prereg verdict |
|---|---|---|---|---|---|---|
| lex_frozen | .637 | .626 | .673 | .939 | .684 | PARTIAL (design-CRC risk .169 on finqa) |
| raw_answer_token_prob | .698 | .739 | .612 | .622 | .638 | PARTIAL (drop .074) |
| raw_ptrue | .639 | .854 | .663 | .768 | .582 | GENERALIZES (design-λ coverage ≈0) |
| lex_platt | .471 | .626 | .673 | .939 | .684 | GENERALIZES* |
| V8_refit | .653 | .898 | .772 | .786 | .632 | GENERALIZES |
| V9_cheap | .731 | .869 | .589 | .727 | .697 | PARTIAL (drop .060) |
| V9_full | .786 | .880 | .750 | .746 | .735 | GENERALIZES (drop .042) |
| abl_logprobs_only | .690 | .791 | .675 | .649 | .676 | GENERALIZES |
| abl_ptrue_only | .601 | .854 | .663 | .768 | .582 | GENERALIZES |
| abl_semantic_entropy_only | .653 | .460 | .665 | .603 | .626 | GENERALIZES (abstains on everything under CRC) |

No arm had an AUROC CI that includes 0.5 on any set. Exact CIs, ECE, Brier, AURC, selective accuracy and CRC (design λ and per-set cal-refit λ) are in results.json.

*The mechanical rule ("the GENERALIZES arm with the highest mean AUROC") picks **lex_platt**. That pick is degenerate. lex_platt is a monotone rescaling of lex_frozen, so it ranks items identically. Its design OOF AUROC was .47, and its "negative drop" just reflects how bad that design score was. Its mean is lifted by jfinqa (.939), where the lexical cue probably reflects the dataset's answer format rather than real uncertainty: under the official EM label, its jfinqa AUROC is only .507. Its design-λ CRC also has 0 coverage everywhere, so it abstains on every item. I report the rule's output but do not endorse it.

## Key paired differences (95% bootstrap CI, item level)
- V9_full − V9_cheap: secq [+.089, +.232]; jfinqa [−.009, +.045]; finqa [−.011, +.089].
- raw_answer_token_prob − V9_cheap: secq [−.044, +.088]; jfinqa [−.138, −.074]; finqa [−.123, +.002].
- V8_refit − V9_cheap: secq [+.096, +.271]; jfinqa [−.017, +.131]; finqa [−.146, +.013].

## Cost per item (USD, test sets)
- V7: $0.03–0.11
- V9_cheap: $0.04–0.13
- V8_refit: $0.13–0.30
- V9_full: $0.21–0.46

## Plain-language verdict
- **V9_full is the only well-performing signal that is stable.** It scores AUROC .73–.75 on all three new sets (design .79). Its design-λ CRC keeps realized risk ≤ .057 at 31–41% coverage.
- **V9_cheap is partially overfit.** It led on design (.73) but fell to .59 on secq.
- **The raw answer-token probability arm** is weak everywhere (.61–.64) and is labelled PARTIAL. It is a fair cheap baseline, but no better than that.
- **The oodsec reference was optimistic for every p(true)-based arm** (.85–.90 vs .58–.79 here).
- **Rankings are unstable across sets:** Kendall τ vs design is −.05 to +.40, and −.44 on jfinqa.

## What the submission should claim
- "Across three held-out financial QA sets (SEC XBRL, JFinQA, FinQA), the full V9 verifier gave AUROC 0.73–0.75 for error detection. Its frozen conformal threshold kept realized error ≤6% at 31–41% coverage."
- The cheap variant and raw token probability do not generalize as well.
- Do NOT claim the oodsec AUROC ≈ .87 as typical.

## Limitations
- Per the pilots, jfinqa and secq are easier than the 30–70% target; the sets were frozen anyway.
- FinQA/JFinQA may have leaked into pre-training. secq is built from XBRL facts dated before the model's Sep 2025 cutoff.
- ~154 jfinqa programs use unrounded operands, and one table is inconsistent.
- The FinQA gold scale is often missing, so the EM sensitivity results differ markedly.
- The rag baseline sometimes gives empty predictions; these were not repaired.

## Spend
About $1.62 of Nebius for this study. The cumulative ledger is $9.63 of the $20 cap.
