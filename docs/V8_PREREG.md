# V8 pre-registration (committed before any V8 run)

**Design slice**: `docs/v8/design.json`, n=648, sha256 `2728213ad1bba18f2228cbbdffc2a89aa60ee2db0b41adb0303ebfe91c5fc4f7`.
TAT-QA dev, seed-2026 order positions 1020–1667, shuffled with NEW seed 8008. Disjoint (checked) from dev positions 0–1019,
test500, holdout_v1, contaminated, pilot manifest, V7.1 design300/eval400/holdout300 and the abstention-fit dev ids.
Note found while building it: the frozen abstention fit (`bench/calib/abstention_v7.json`) used dev rows that are exactly
dev positions 0–149 of this order, i.e. 130 of them overlap the V7.1 eval400 slice (20–419). Disclosed; it does not touch V8.
**Hold-out 720–1019 stays CLOSED**; test500 is never touched.

**Run**: one system `agent_v8` (V8=1) on Nebius `nvidia/Nemotron-3_5-Lightning`, NEBIUS_STRICT=1, T=0 for V7 and pointer-0,
K=5 pointer samples at T=0.7 (declared), LLM_CACHE=0, budget guard NEBIUS_BUDGET_USD=9 (cumulative ledger).
Each item records V7, A, B, B+C answers from the SAME V7 run → exactly paired comparisons, same provider/model.

**Arms** (flags = fields of the output): `v7` (base), `A` pointer@T0 + executor (fallback V7), `B` majority vote over the
6 pointer samples (fallback V7), `BC` = B + one repair call only when no sample validates.

**Metrics** (all arms): official TAT-QA EM/F1 with scale (primary), semantic (secondary), fixed/broken vs V7, McNemar exact p,
paired bootstrap 95% CI of ΔEM (10k), calls/item, latency, cost per correct (pointer-stage cost attributed from traces).
Confidence (same definition for both arms when compared): V7 `lex` (frozen) vs V8 logistic on [agree, ptr0_valid,
ptr0_agrees_vote, v7_agrees_vote, v7_gate_passed, lex] fitted on design with 5-fold CV (out-of-fold scores reported):
AUROC, ECE(10 bins), Brier, AURC, coverage/selective EM at frozen 0.809 (lex) and at a threshold fixed on design.

**Acceptance**: ΔEM > 0 AND broken ≤ fixed/3. Confidence change: AUROC and ECE improve, EM not hurt, bootstrap CI of the
AUROC difference excludes 0. When a combined candidate exists: freeze config hash, STOP before hold-out, wait for Code Reviewer.

## Final config before hold-out (round 2, after review of PR #13)
- Answer: V7 unchanged. PRIMARY confidence `bench/calib/v8_conf.json` (sha256[:16] 70926c2c67b1f17a), K=5, threshold 0.5189.
  SECONDARY `bench/calib/v8_conf_k0.json` (ceaed3cbc6de5dc4), K=0 (pointer-0 only), threshold 0.4901. Both from `python -m bench.v8_freeze`
  (full-design refit; threshold = OOF cut matching frozen-lex@0.809 coverage). Features `bench/v8_r2.py:feats_k`:
  [agree, ptr0_valid, ptr0_agrees_vote, v7_agrees_vote, v7_gate_passed, lex].
- Baselines on hold-out: frozen lex@0.809; lex Platt and lex isotonic fitted on the whole design slice; raw agreement (`agree`).
- Claim limited to ranking/abstention (AUROC, AURC, Brier, selective EM at matched coverage, paired bootstrap ΔAUROC CI). ECE reported, no calibration claim.
- Hold-out: ONE run of agent_v8 on docs/v71/holdout300.json (dev 720–1019, n=300), same provider/model/env as V7 (Nebius
  Lightning, NEBIUS_STRICT=1). No tuning afterwards; results published as-is in docs/V8_HOLDOUT_RESULTS.md. If V8 does not beat
  lex, V7's confidence is kept.
- Folds were by question (648 q / 260 tables); disclosed. Config commit SHA: see the commit that adds this line's successor note.
