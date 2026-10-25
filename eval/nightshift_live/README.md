# Nightshift live receipts (2026-10-25, Nightshift 1.2.7 on the author's Windows PC)

Data: synthetic DuckDB snapshot (ZETARIS_BACKEND=sample, SAMPLE_MODE=false so the LLM path is live). LLM_FALLBACK=none. Raw receipts in this folder; no prompts or keys are stored (only prompt_chars, routed_model, usage, latency).

Ad-hoc checks before the runs: `meterless/fast` was coerced to `meterless/auto` by the app policy and routed to `nvidia/nemotron-3.5-bolt-e4b` (not Lightning), so the tiers request exact ids. Explicit ids routed as requested: Lightning 0.53 s, Ultra 0.67 s (tiny prompt). Ultra with thinking on hit finish_reason=length on every S2 call in run 1 (run1-* files); S2 now sends enable_thinking=false.

| run | calls | routed_model | n | max latency s | sum latency s | errors | finish |
|---|---|---|---|---|---|---|---|
| receipts-example-001 | s1 pin_check | nvidia/nemotron-3.5-lightning-30b-a3b | 1 | 1.4 | 1.4 | - | stop |
| receipts-example-001 | s2 pin_check | nvidia/nemotron-3-ultra-550b-a55b | 1 | 0.7 | 0.7 | - | stop |
| receipts-example-001 | s2 agent | nvidia/nemotron-3-ultra-550b-a55b | 3 | 2.2 | 6.0 | - | stop |
| receipts-example-001 | s1 agent | nvidia/nemotron-3.5-lightning-30b-a3b | 45 | 14.2 | 127.3 | - | stop |
| receipts-example-002 | s1 pin_check | nvidia/nemotron-3.5-lightning-30b-a3b | 1 | 0.5 | 0.5 | - | stop |
| receipts-example-002 | s2 pin_check | nvidia/nemotron-3-ultra-550b-a55b | 1 | 0.7 | 0.7 | - | stop |
| receipts-example-002 | s2 agent | nvidia/nemotron-3-ultra-550b-a55b | 3 | 1.9 | 3.9 | - | stop |
| receipts-example-002 | s1 agent | nvidia/nemotron-3.5-lightning-30b-a3b | 43 | 21.4 | 161.5 | - | stop |
| receipts-example-002 | s1 agent | None | 2 | 22.2 | 43.9 | HTTPError: HTTP Error 502: Bad Gateway | None |
| receipts-example-003 | s1 pin_check | nvidia/nemotron-3.5-lightning-30b-a3b | 1 | 0.4 | 0.4 | - | stop |
| receipts-example-003 | s2 pin_check | nvidia/nemotron-3-ultra-550b-a55b | 1 | 0.7 | 0.7 | - | stop |
| receipts-example-003 | s2 agent | nvidia/nemotron-3-ultra-550b-a55b | 2 | 5.5 | 7.4 | - | stop |
| receipts-example-003 | s1 agent | nvidia/nemotron-3.5-lightning-30b-a3b | 28 | 7.6 | 66.2 | - | stop |
| run1-receipts-example-001 | s1 pin_check | nvidia/nemotron-3.5-lightning-30b-a3b | 1 | 0.6 | 0.6 | - | stop |
| run1-receipts-example-001 | s2 pin_check | nvidia/nemotron-3-ultra-550b-a55b | 1 | 1.4 | 1.4 | - | length |
| run1-receipts-example-001 | s2 agent | nvidia/nemotron-3-ultra-550b-a55b | 4 | 4.8 | 12.6 | - | length |
| run1-receipts-example-001 | s1 agent | nvidia/nemotron-3.5-lightning-30b-a3b | 39 | 6.9 | 62.9 | - | stop |
| run1-receipts-example-001 | s1 agent | None | 2 | 22.1 | 44.2 | HTTPError: HTTP Error 502: Bad Gateway | None |
| run1-receipts-example-002 | s1 pin_check | nvidia/nemotron-3.5-lightning-30b-a3b | 1 | 0.5 | 0.5 | - | stop |
| run1-receipts-example-002 | s2 pin_check | nvidia/nemotron-3-ultra-550b-a55b | 1 | 0.7 | 0.7 | - | length |
| run1-receipts-example-002 | s2 agent | nvidia/nemotron-3-ultra-550b-a55b | 4 | 13.8 | 30.3 | - | length |
| run1-receipts-example-002 | s1 agent | nvidia/nemotron-3.5-lightning-30b-a3b | 42 | 6.1 | 63.8 | - | stop |
| run1-receipts-example-003 | s1 pin_check | nvidia/nemotron-3.5-lightning-30b-a3b | 1 | 0.4 | 0.4 | - | stop |
| run1-receipts-example-003 | s2 pin_check | nvidia/nemotron-3-ultra-550b-a55b | 1 | 0.7 | 0.7 | - | length |
| run1-receipts-example-003 | s2 agent | nvidia/nemotron-3-ultra-550b-a55b | 2 | 8.3 | 16.5 | - | length |
| run1-receipts-example-003 | s1 agent | nvidia/nemotron-3.5-lightning-30b-a3b | 23 | 5.0 | 38.0 | - | stop |

Outcomes (run 2): out_1.json: success; out_2.json: success; out_3.json: partial
