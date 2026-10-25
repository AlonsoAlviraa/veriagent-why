# V7.1 — development results (TAT-QA dev only)

**Status: DEVELOPMENT, post pre-registered run.** This does not modify or reinterpret the pre-registered V7 result (65.8%). No test500 / pilot / gold-test items were used.

## Setup
- Arms: `agent_mk` (frozen V7) vs `agent_mk71` (`V71=1`: structured `{answer_type,value,scale}`, extractive spans w/ fuzzy match, expanded claim gate, semantic metric).
- Items: 400 TAT-QA **dev** items, seeded dev order (seed 2026) positions 20..419 (`docs/v71/eval400.json`). Positions 0..19 were reserved for smoke/debug (one fix — numeric table spans get the V7 scale/format post-step — was made after the 3-item smoke, before this run; no changes after it).
- Nebius, `NEBIUS_STRICT=1`, `nvidia/Nemotron-3_5-Lightning`, T=0, 4 shards, paired on identical items, no cache.
- Run cost: ≈ $0.17 (ledger 5.944 → 6.119 USD cumulative; cap 15).

## Results (n = 400 paired)
| metric | V7 | V7.1 |
|---|---|---|
| EM | **68.75%** | 58.75% |
| F1 | 78.26 | 67.89 |
| sem (secondary, never replaces EM) | 79.50% | 76.50% |
| coverage (non-empty) | 99.5% | 99.25% |
| selective EM | 69.1% | 59.2% |

- EM paired: V7.1 fixes 24, regresses 64; Δ = −10.0 pp, bootstrap 95% CI [−14.5, −5.5], exact McNemar p < 0.001. **V7.1 is significantly worse on EM.**
- sem paired: fixes 32, regresses 44; Δ = −3.0 pp, CI [−7.25, +1.25], p = 0.21 (n.s.).
- Gate blocked 3 answers.

## V7 error categories (heuristic) and how many V7.1 fixes
| category | V7 errors | fixed by V7.1 |
|---|---|---|
| span | 46 | 11 |
| scale | 42 | 6 |
| format only (sem ok) | 17 | 1 |
| arithmetic/other | 14 | 2 |
| sign | 4 | 3 |
| empty | 2 | 1 |

## Regressions (64) — main patterns (full list in `docs/v71/analysis.json`)
1. **Over-long extractive spans**: the verbatim quote (whole sentence) is returned as the answer instead of the minimal span (~20 cases). The span_length gate only checks "answer ⊆ cited span", not minimality.
2. **"Which year" questions answered with the value** instead of the year (~15). The year_only repair does not fire when the model types the answer as a number span.
3. **Spurious scale on numeric spans** (`percent`/`thousand`/`million` when gold is ""), partly caused by the scale post-step extended to numeric spans after the smoke.
4. Multi-span collapsed into a single string / arithmetic (e.g. "35,121 and 30,973", "3995" instead of two values).
5. Sign the gate wrongly flips (1046abe8: −4697 vs 4,697).

## Conclusion
As implemented, V7.1 does not improve on V7 on dev; the frozen V7 stays the reference. The sign rule and the empty/evidence block do help on their small categories. Any V7.1b fix (minimal-span selection, year-question routing, scale only when evidence unit is explicit and the question is numeric, keep multi-span lists) must be evaluated on a **new, disjoint** dev slice, not these 400 items.
