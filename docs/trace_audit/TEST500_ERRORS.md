# test500 agent_mk: failure patterns in the audit.json traces (primary run)

Read only. Source: `bench/results/test500/traces-agent_mk/**/*.audit.json` (500 traces, code_rev 74591af, NVIDIA,
pre-registered primary run). For retried items the trace is the final, non-error attempt. Nothing in the primary run
was changed or rerun because of this audit. Classifier: `classify_errors.py` (deterministic heuristics over answer,
gold, scale, scores, gate verdict and the prompt context in the trace). Per-item table: `test500_primary_errors.csv`.
Categories are heuristic: read them as patterns with approximate counts, not hand-labelled ground truth.

**171 wrong items out of 500 (EM 0.658).** By answer type: span 89, arithmetic 44, multi-span 31, count 7.

## Primary failure pattern (one per item)

| pattern | n | what it means | example (item id: question → pred vs gold) |
|---|---|---|---|
| span_too_long | 43 | right fact, extra words beyond the gold span | `0a5bf43b11e9` "In which year was intangible assets negative?" → "September 28, 2018" vs "2018"; `05f99016137c` → "Year Ended June 30" vs "June 30" |
| span_truncated | 27 | right fact, gold span cut short | `0589a3d4e18b` → "12.5 years" vs "12.5 years as of the acquisition date"; `0ef48d6dc0be` drops "(DSIR)" |
| wrong_operands_or_arithmetic | 15 | computed number not near gold, not a context number | `276815a7f82a` IPTV subscriber change → 19314 vs 91476; `31a78c37b86b` → 4.76% vs 0.1% (relative vs absolute change) |
| scale_units | 13 | right digits, wrong or missing scale | `2238ca90aabc` → "-39.5" vs "-39.5 million"; `27f6efd18696` EPS → "5.8 thousand" vs "5.8" |
| wrong_row_column_or_span | 12 | answer copied from the wrong cell/passage | `4cac8704d20d` capital 2019 → 83692 vs 66,128 thousand (other row/col); `57e30b537266` "Why did service revenue increase?" → "2 percent" |
| multi_span_partial | 11 | some of the spans right, others missing/wrong | `0103b1e44ef0` drops "Sales-based Milestones and"; `12706693199f` gives a generic reason instead of the 2 listed |
| wrong_sign | 10 | magnitude right, sign flipped (order of subtraction) | `4ae88a16a8a9` → -50054 vs 50054 thousand; `63c46efdd387` → -239000 vs 239000; `200c49c9af38` → -17.7% vs 17.7% |
| partial_span | 10 | overlapping but different span (F1>0) | `2870200c1799` cause of prepaid increase: quotes the amount, not the driver |
| off_target_answer | 9 | answer of the wrong kind | `05364cef9fe8` "What caused…" → "19666 million"; `38174239d86b` ROFE → "0.1 million" vs "5 bps" |
| copied_context_number_not_computed | 7 | returned a raw table number where a computation was asked | `41a751bd0e11` → 48915 vs 10705 million; `7cfbd3635aa4` count → 2 vs 1 |
| wrong_year_comparison | 5 | min/max over years picks the wrong year | `982e69eae13a` smallest fair value: the calc step said **2018** (correct), the writer step answered 2019; `05e53df93fcd` → 2018 vs 2019; `1a255e23c871` → "FY181" (typo) vs "FY18" |
| format_list_for_scalar | 4 | Python list returned for a scalar/count | `0ff4afd650a5` → "['3','4','4']" vs 3; `4c309d1eb940` → "['9174','9170']" vs 18344 (sum not taken) |
| format_normalization | 2 | F1 = 1.0 but EM = 0 (separator/format only) | `08bfe3f76b4b` "2019 and 2018, 2018 and 2017" vs the same two spans |
| rounding | 2 | within 2% of gold | `857a9562bbcd` → 40.99% vs 41% (calc step had 41); `4dcb5786a1d4` → 16.62 vs 16.52 percent |
| empty_answer | 1 | no answer, evidence empty, gate still PASS | `c3ef3efb4a4e` (gold 2019, 2018) |

Span-boundary problems (too long + truncated + partial + multi-span partial + format) are **93/171 = 54%** of
failures: mostly "right place, wrong boundaries" against TAT-QA's strict EM, not hallucinations.
Number-handling errors (scale 13, sign 10, rounding 2, list-for-scalar 4) are 29; real reasoning errors (wrong
operands/arithmetic, wrong cell, copied number, wrong year, off-target) are about 48.

## Cross-cutting signals (an item can have several)

- **Gate let a wrong answer through: 140/171 wrong items had gate PASS.** Across all 500: PASS → 313 right / 140 wrong
  (precision 0.69, barely above base 0.658); REJECT → 16 right / 31 wrong. The Claim Gate checks traceability of quotes,
  not the correctness of span boundaries, scale, sign or operands, so it cannot catch the dominant patterns above.
- **Overconfident when wrong: 163/171 wrong items had self-reported confidence ≥ 0.95.** 133 had both gate PASS and
  raw ≥ 0.95. That is the calibration finding in the report (mean conf 0.97 vs accuracy 0.66).
- **Abstention lets most errors through:** 128 of the 171 wrong items still clear lex ≥ 0.809 (they are answered).
- **Empty evidence treated as valid: 1 item** (`c3ef3efb4a4e`, empty answer + no evidence + PASS). Rare, but it is a
  gate bug: empty evidence should never PASS.
- **Calc step right, final answer wrong: at least 2 items** (`982e69eae13a`, `857a9562bbcd`). Under-counted: the
  traces store only the head of the calc reply ("their expressions and observations were not stored").

## Implications (not applied to the primary run)
1. Span normalisation / boundary trimming (answer the minimal span; strip "Included in", "Year Ended") is the largest
   lever, but would be a new system and needs a new held-out split.
2. Deterministic checks the gate could add: scale presence for monetary answers, sign check against the question's
   "from X to Y" order, scalar type for count/arithmetic, never PASS on empty evidence.
3. The confidence signal needs a correctness-sensitive component; gate PASS + raw confidence carry little signal.

## Replica (post-hoc, Nebius, both arms, 8 replicates)

Read only, same classifier, unchanged. Source: `bench/results/test500_nebius/traces-agent_mk/agent_mk-{0..7}/**/*.audit.json`
(8 × 500 traces, code_rev bc0c8de, Nebius `nvidia/Nemotron-3_5-Lightning`, T=0). The shard id filter was not applied, so
each of the 8 shards is a full 500-item replicate. Per-item tables: `replica_nebius_agent_mk_r{0..7}.errors.csv`,
plus `replica_nebius_rag_r0.errors.csv` for one rag replicate. Same caveat: heuristic patterns, not hand labels.

**agent_mk wrong items per replicate: 160, 162, 170, 163, 163, 162, 164, 167 (mean 163.9; primary 171).**

| signal | primary (NVIDIA) | replica mean (range over 8) |
|---|---|---|
| span-boundary share of failures (too long + truncated + partial + multi-span partial + format) | 93/171 = 54% | 87.3 = 53% (85–90; 52–55%) |
| number handling (scale, sign, rounding, list-for-scalar) | 29 | 31.9 (29–35) |
| wrong with gate PASS | 140 | 132.1 (128–138) |
| wrong with raw confidence ≥ 0.95 | 163 | 148 (142–154) |
| empty evidence passed the gate | 1 | 1.4 (0–3) |
| plan/calc step had the gold, writer changed it | ≥ 2 | 5.0 (4–7) |

- The top three primary patterns are identical in all 8 replicates: span_too_long (36–38), span_truncated (27–32),
  scale_units (14–15). Then wrong_sign (10–12), wrong_operands_or_arithmetic (10–14), wrong_row_column_or_span (9–12).
- Error identity is stable: 148 items are wrong in all 8 replicates, 187 wrong in at least one. Of the 171 primary
  (NVIDIA) failures, 137 are wrong in every Nebius replicate and 20 are right in every one.
- The "empty evidence still PASS" gate bug recurs (0–3 items per replicate), so it is not a one-off.
- **rag, one replicate (r0):** 241 wrong (EM 0.518). Its profile differs from agent_mk: wrong operands/arithmetic 44,
  rounding 35, span_truncated 32, span_too_long 28, empty answer 26, scale 16, list-for-scalar 14. Single-shot rag
  loses mostly on computation and on returning an empty answer (26; 22 of those still had an expression); agent_mk's calc step removes most of
  that, leaving span boundaries as its main loss. rag traces carry no Claim Gate, so the gate rows do not apply to it.
- Conclusion: the failure profile in the primary audit is a property of the system, not of the NVIDIA endpoint or of
  one run. Nothing here was used to change the shipped system.

