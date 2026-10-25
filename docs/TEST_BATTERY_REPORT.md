# Test battery report

Branch `feat/test-battery`, cut from `main` `0b7aac6`. Date: 25 Oct 2026.

Everything here runs offline, with no network and no spend. The PR only touches `tests/`, `bench/`, `scripts/` and `docs/`. No app code was changed: the bugs found are pinned as `xfail(strict=True)` tests and listed below for a decision.

## Counts (exact)

**Full suite**: `pytest -q`, Python 3.13.5, with `requirements.txt` and `bench/requirements-bench.txt` installed.
- Result: **4749 passed, 56 xfailed, 0 failed, 0 skipped**, in 54.9 s.
- On `main` the same suite is 334 passed, 1 skipped, 49 xfailed. The battery adds 4414 passed and 7 strict xfails. The skipped test now runs because the TAT-QA data is present.

| File (`tests/battery/`) | Passed | Xfail (strict) | What it checks |
|---|---|---|---|
| test_claim_gate_battery.py | 1745 | 0 | Claim Gate / POST /verify over 2 metrics × 16 segments × 7 windows on the DuckDB snapshot (details below). |
| test_scorer_battery.py | 1268 | 0 | TAT-QA official EM/F1 and semantic_correct edge cases: scales, percent vs ratio, signs, thousands separators, multi-span, lists. |
| test_confidence_math_battery.py | 1043 | 0 | AUROC vs brute-force pair counting, AURC, ECE, CRC lambda, lex-threshold grid, selective accuracy. |
| test_secret_scan_battery.py | 200 | 0 | Every secret pattern on 25 synthetic secrets built at runtime; clean look-alikes not flagged; forbidden files; scan of a throwaway git repo fails on a key left only in history and never prints it. |
| test_ledger_battery.py | 65 | 0 | Nebius spend ledger (details below). |
| test_provenance_battery.py | 39 | 0 | Frozen split and dataset sha256; ids unique and present; cal/test/pilot disjoint and grouped by document; all sets pairwise disjoint; holdout and test500 hashes; test_gold not in train/dev and not in any fixture; a dirty git tree aborts real runs. |
| test_tatqa_gate_battery.py | 28 | 3 | TAT-QA gate planted traps on dev, safe_eval allow/deny cases, gate cases, pinned limits. |
| test_sample_mode_e2e_battery.py | 15 | 0 | The 3 demo scenarios in a credential-free subprocess equal the committed `output_examples/` and their reruns. |
| test_planted_traps_battery.py | 11 | 4 | Planted-trap script as a test, its determinism, pinned narrative limits. |
| **Total** | **4414** | **7** | |

**Claim Gate battery details.** For each cell:
- the true value comes from independent string-built SQL;
- the exact claim must be green;
- a value shifted ± beyond tolerance must be red, and a value inside tolerance must stay green;
- tampered, foreign or missing row ids must be red;
- unsupported metric or segment SQL must be red;
- the SQL hash must be stable;
- mixed receipt summaries and narrative numbers are also checked.

**Ledger battery details:**
- the cost formula, for every priced model;
- unknown models are refused;
- 30 random reserve/settle sequences;
- 10 concurrency runs of 40 threads, where reservations never exceed the budget;
- a failed call books the worst case, and a 4xx books 0.

## Planted-trap evaluation

Reproduce with:
- `python scripts/planted_traps.py --n 800 --seed 20261025`, which writes [`test_battery/planted_traps.json`](test_battery/planted_traps.json);
- `python scripts/tatqa_gate_traps.py`, which writes [`test_battery/tatqa_gate_traps.json`](test_battery/tatqa_gate_traps.json).

All CIs are Wilson 95% CIs.

### 1. Structured claims → POST /verify (DuckDB snapshot), 800 items

- **Detection (red):** 400/400 = **100%**, CI [99.05%, 100%].
- **Traps passed as green:** 0/400.
- **False alarms (red on a correct claim):** 0/400 = **0%**, CI [0%, 0.95%].
- **Controls not green:** 0/400.

Trap types: shift_large, shift_just_outside_tol, ratio_as_percent, segment_swap, window_swap, metric_swap, inverse_rate, foreign_row_ids, fabricated_row_ids.
- Each type has 44–45 items and each is 100% red.
- Control types are exact, rounded_1dp, rounded_0dp_count and jitter_inside_tol: 100 each, all green.

Caveat: these are well-formed structured claims, and the gate recomputes them by SQL, so a perfect score is expected. The test does not measure how well an LLM turns prose into claims. Errors smaller than the tolerance (±0.5 pp, 1%) are undetectable by design.

### 2. Narrative number check (`check_narrative`), 800 items

- **Traps flagged:** 324/400 = **81.0%**, CI [76.9%, 84.5%].
- **Controls flagged (false alarms):** 173/400 = **43.3%**, CI [38.5%, 48.2%].

| Type | n | Flagged | 95% CI |
|---|---|---|---|
| trap wrong_plain / wrong_pct / wrong_thousands_sep / digit_transposition | 77 / 85 / 92 / 70 | 100% each | lower bound ≥ 94.8% |
| trap spelled_out_wrong ("roughly one thousand") | 76 | **0%** | [0%, 4.8%] |
| control plain / pct_1dp / pct_2dp | 95 / 62 / 70 | 0% | upper bound ≤ 5.8% |
| control thousands_sep ("1,234") | 29 | **100%** | [88.3%, 100%] |
| control with_year ("In 2026 …") | 62 | **100%** | [94.2%, 100%] |
| control with_date ("On Sep 15 …") | 52 | **100%** | [93.1%, 100%] |
| control ratio_form (0.8725 for 87.25%) | 30 | 100% | [88.7%, 100%] (arguably correct) |

The mix of types is synthetic, so the 43% false-alarm rate depends on that mix. The per-type rows are the meaningful numbers.

### 3. TAT-QA Claim Gate (`bench.tatqa.gate`) on 702 real dev arithmetic questions

TAT-QA dev is a development set.

- **Traps flagged:** 1805/2253 = **80.1%**, CI [78.4%, 81.7%].
- **Gold derivation false alarms:** 6/702 = **0.85%**, CI [0.39%, 1.85%].

| Type | n | Flagged | 95% CI |
|---|---|---|---|
| answer ≠ value of its expression | 516 | 100% | [99.3%, 100%] |
| evidence quote with a fabricated number | 702 | 100% | [99.5%, 100%] |
| one operand changed 7–30% | 571 | 88.8% | [85.9%, 91.1%] |
| numeric answer, no expression, not derivable | 464 | **17.2%** | [14.1%, 20.9%] |
| control: gold derivation + gold answer + real row | 702 | 0.85% flagged | [0.39%, 1.85%] |

The 6 gold false alarms break down as follows:
- **3: percent literals.** `(1-15%)*($2.2/15%)` is evaluated with 15 instead of 0.15.
- **2: accounting parentheses in the gold.** In `-114 - (71)` the gold treats `(71)` as negative.
- **1: mixed scale words.** `60.3 million + 32,137 thousand`.

Operand-changed misses happen when the changed number is also in the context or is a free small integer. That is a real limit of number-in-context checks.

## Bugs and decisions needed (not fixed here: app code or frozen V10 code)

1. **`check_narrative` thousands separators** (app/checks/claims.py). `1,234` is read as 1 and 234, so a correct number is flagged. The fix is a one-line regex change. Pinned by `test_narrative_thousands_separator_supported`.
2. **`check_narrative` years and dates** are treated as unsupported numbers, so any memo sentence containing "2026" or "Sep 15" is flagged. Decision: whitelist dates, or require the writer to omit them. Pinned.
3. **`check_narrative` spelled-out numbers** are not checked ("roughly one thousand"), so those traps are missed. Decision: forbid them in the writer prompt, or parse them. Pinned.
4. **`bench.tatqa.safe_eval` percent literals.** `15%` evaluates as 15, which caused 3 of 6 gold false alarms on dev. The fix would change `agent_v9` behaviour, which V10 has frozen, so this is not fixed. Pinned.
5. **`safe_eval` scale words** are stripped, not applied. Pinned.
6. **`bench.tatqa.traceable` is weak in dense contexts.** It accepts any number within tolerance of the pairwise +, −, ×, ÷ results of up to 120 context numbers. Only 17.2% of fabricated, expression-free answers are caught. Decision: require an expression for numeric answers, or tighten the tolerance. Pinned.
7. **`bench.v9_final.crc_lambda` raises `StopIteration`** when alpha < 1/(m+1), because no threshold is feasible. `v9_gen_analysis` already maps this to `inf`, so V9 numbers are unaffected. A clean return of `inf` would be safer. Both behaviours are tested.
8. **`make setup` + `make test` fails on a clean clone** (6 tests need `bench/requirements-bench.txt`). See [CLEAN_CLONE_CHECK.md](CLEAN_CLONE_CHECK.md).
9. **Split-id hash format is undocumented.** `ids_sha256` in `bench/splits/*.json` is sha256 of the ids joined with `\n`, with no trailing newline. That is now tested; it should be stated in the split files' docs.

## How to run

```
pip install -r requirements.txt -r bench/requirements-bench.txt
python -m pytest -q tests/battery        # 4414 passed, 7 xfailed (~45 s)
python -m pytest -q                      # 4749 passed, 56 xfailed
```

Some tests need TAT-QA data (`data/bench/tatqa`, via `make data` / bench download) and skip cleanly without it.
