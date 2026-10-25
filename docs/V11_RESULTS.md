# V11 results — fresh benchmark (TableBench), single pre-registered run

**Verdict under the pre-registered rules (docs/V11_PREREG.md §7): WORKS.** A1, A2 and A4 hold, and A3 also holds. RAG does not win.
Raw output: `docs/v11/results_v11.json`, produced by `python -m bench.v11_analysis "docs/v11/runs/v11_*.jsonl"`.

## Run facts
- **One run, no tuning, no re-runs.** The pre-registration was committed as `dbc2233`, and only then were any model calls made (run started 17:42 CET, 25 Oct).
- **Rows:** 722 rows = 361 items × 2 systems (agent_v9, rag), in 6 shards. All shards finished and no rows are missing. Every row carries code_rev `dbc2233`, dirty=false.
- **Config:** config_sha256 `52d302eb…9173`, the frozen V9_full model and λ = 0.683. Nothing was refit.
- **Cost:** Nebius ledger $13.65 before the run and $14.17 after, so the run cost about **$0.53** (the cap was $5).
- **Empty answers** (no run errors occurred): V7 27, RAG 31. They are scored as wrong, and for V7+V9 they count as abstentions, as pre-registered.
- **Integrity:** sha256 of every row, trace and data file is in `docs/v11/MANIFEST.sha256`. The traces are in `docs/v11/runs/traces_v11.tar.gz`. The secret scan is clean (the only hit is the redaction-policy descriptor string).

## Answers (semantic correctness, n = 361; paired bootstrap 95% CI, B = 2000)
| System | Semantic | 95% CI | EM |
|---|---|---|---|
| V7 (final answers) | **48.2%** | 43.2–53.7 | 39.1% |
| Plain RAG (reference) | 32.7% | 28.0–37.7 | 24.4% |
| Trivial rule (median cell) | 5.5% | 3.3–8.0 | 1.7% |

The paired difference V7 − RAG is **+15.5 pp [+11.1, +20.2]**, so **A1 holds**. V7 − trivial is +42.7 pp [+37.7, +47.9].

## Confidence layer (V9_full, frozen λ = 0.683)
| | Value | 95% CI |
|---|---|---|
| Coverage (answered) | 36.6% | (abstains on 63.4%) |
| Selective accuracy | **77.3%** | 69.6–84.1 |
| Selective acc − V7 acc (answer everything) | +29.1 pp | +22.5, +35.7 |
| Realized risk (wrong answers given / n) | 8.3% | target α = 0.10, so **A3 holds** |
| AUROC V9_full | **0.834** | 0.790–0.874 |
| AUROC V7 confidence_det | 0.673 | 0.623–0.723 |
| AUROC traceability gate | 0.638 | 0.591–0.682 |
| AUROC diff V9 − V7 confidence | — | +0.109, +0.218 |

**A2 holds.** The V9 AUROC here (0.83) is far above V10's hard sets (0.67 / 0.66), and close to the oodsec hold-out (0.82).

## Net score (+1 correct, −1 wrong, 0 abstain)
| V7+V9 | V7 (always answers) | RAG (always answers) |
|---|---|---|
| **+0.199** | −0.036 | −0.346 |

V7+V9 − RAG = +0.546 [+0.460, +0.637], so **A4 holds**. V7+V9 − V7 = +0.236 [+0.155, +0.313].

## By subtype (semantic accuracy; V9 coverage)
| Subtype | n | V7 | RAG | V9 coverage |
|---|---|---|---|---|
| Aggregation | 49 | 46.9% | 12.2% | 44.9% |
| ArithmeticCalculation | 49 | 65.3% | 38.8% | 49.0% |
| Comparison | 25 | 60.0% | 52.0% | 44.0% |
| Counting | 50 | 16.0% | 14.0% | 8.0% |
| Domain-Specific | 13 | 30.8% | 30.8% | 30.8% |
| MatchBased | 21 | 100% | 100% | 100% |
| Multi-hop FactChecking | 22 | 81.8% | 81.8% | 63.6% |
| Multi-hop NumericalReasoning | 46 | 37.0% | 10.9% | 30.4% |
| Ranking | 8 | 75.0% | **87.5%** | 25.0% |
| StatisticalAnalysis | 32 | 9.4% | 0.0% | 9.4% |
| Time-basedCalculation | 46 | 58.7% | 39.1% | 28.3% |

## Failures and honest limits
- **Wrong V7 answers:** 187 / 361. V9 **abstained on 157** of them but **answered 30 confidently wrong**. Examples:
  - median executions: gold 57, V7 313, p = 0.87
  - % change: gold 5.25, V7 −5.25 (sign error), p = 0.83
  - total daily flights: gold 115.7, V7 1157 (×10 / scale error), p = 0.73
  - goal %: gold 18.87%, V7 11.32, p = 0.73
  - London funding: gold 33496, V7 47195, p = 0.83

  The full list is in `results_v11.json` → `failures`. RAG was right on 13 of the 187 items V7 got wrong.
- **High abstention:** 63% overall and 92% on Counting. The system is useful only where it answers, and the abstention is itself the cost.
- **Weak spots:** V7 is weak on Counting (16%) and StatisticalAnalysis (9%; std/correlation that the calculator does not compute well). RAG beats V7 on Ranking, but n = 8.
- **Table-only data:** TableBench has no text paragraphs, so the "text" half of table-text QA is not tested. Its domain is general (not finance), which is the point of the test but also a limit on what it says about financial reports.
- **Single run** with one model (Nemotron 3.5 Lightning on Nebius). There is no repeat-seed variance.
- **Scoring:** EM is TAT-QA's official metric. Semantic correctness is the same numeric scorer as V9/V10, with no LLM judge.
