# Verify v2: three verification ideas on top of agent_mk

All three configs keep agent_mk's claim-gate re-ask (agent_vr skipped it, which gave 28 gate failures versus 17).
Model: Lightning only. Calibration was fitted only on TAT-QA **train** (n=80).

> **Caveats (external review, PR #8 verdict "acceptable as an experiment"):** numeric calibration was fit on train only, but the configs
> were designed after reading dev/eval failures, so TAT-QA dev and InsightBench are development sets (`bench/splits/contaminated.json`).
> The cr +4 EM over mk (110 vs 106 of 150) is inside the ~4 pp T=0 run-to-run noise floor and not significant. The IB calibration map is fit
> on n=29; the critic threshold was chosen on small n. Report AUROC/AURC with ECE (TAT v2 cr AUROC 0.703). Held-out: `docs/HELDOUT_RESULTS.md`.

## Research (verified links)
- CRITIC: tool-interactive critiquing. https://arxiv.org/abs/2305.11738
- Program of Thoughts. https://arxiv.org/abs/2211.12588 ; PAL. https://arxiv.org/abs/2211.10435
- Self-Consistency. https://arxiv.org/abs/2203.11171 ; Universal Self-Consistency. https://arxiv.org/abs/2311.17311
- Chain-of-Verification. https://arxiv.org/abs/2309.11495
- LLMs Cannot Self-Correct Reasoning Yet. https://arxiv.org/abs/2310.01798
- On the self-verification limitations of LLMs. https://arxiv.org/abs/2402.08115
- Let's Verify Step by Step. https://arxiv.org/abs/2305.20050
- Judging LLM-as-a-Judge. https://arxiv.org/abs/2306.05685
- Just Ask for Calibration. https://arxiv.org/abs/2305.14975
- TAT-QA. https://arxiv.org/abs/2105.07624

Takeaway: intrinsic self-verification is overconfident, as agent_vr was. Verification helps when it is grounded in an external signal (tools/execution, sample agreement) and its confidence is calibrated on held-out data.

## Configs (bench/verify2.py)
- **agent_pot**: an independent program-of-thought pass (named operands checked against the context, then safe_eval). If it agrees, confidence goes up. If it disagrees, one revision, then the gate.
  InsightBench: always run the deterministic gate re-ask.
- **agent_sc**: T=0 answer + 2 samples at T=0.6 (chosen on train), majority vote. If all 3 disagree, one adjudication call.
  InsightBench: Writer-sample agreement (ROUGE-1 >= 0.4) reorders insights and drops the unsupported ones.
- **agent_cr**: a CRITIC-style critic with tool results returns p_correct. A revision is used only if p_correct < CR_THRESHOLD (0.6, fitted on train) and it passes the gate. Confidence comes from a train-fitted map.
  InsightBench: the critic flags insights, then one rewrite and the gate.

## Results
**TAT-QA dev n=150, Lightning only**

| config | EM | F1 | citation precision | calibration (det conf) | attempts/item | $ total | s/item |
|---|---|---|---|---|---|---|---|
| agent_mk (post) | 106/150 (0.63-0.77) | 0.826 (0.771-0.879) | 163/249 (0.59-0.71) | ECE 0.146 / Brier 0.243 (n=150, mean conf 0.73, acc 0.71) |  | 0.0279 | 3.9 |
| agent_vr (post) | 79/150 (0.45-0.60) | 0.645 (0.573-0.715) | 159/294 (0.48-0.60) | ECE 0.316 / Brier 0.352 (n=150, mean conf 0.84, acc 0.53) | 1.11 | 0.0387 | 3.6 |
| agent_pot (v2) | 102/150 (0.60-0.75) | 0.777 (0.713-0.840) | 179/267 (0.61-0.72) | ECE 0.188 / Brier 0.228 (n=150, mean conf 0.71, acc 0.68) |  | 0.046 | 5.0 |
| agent_sc (v2) | 100/150 (0.59-0.74) | 0.781 (0.719-0.840) | 169/249 (0.62-0.73) | ECE 0.173 / Brier 0.216 (n=150, mean conf 0.77, acc 0.67) |  | 0.0842 | 11.3 |
| agent_cr (v2) | 110/150 (0.66-0.80) | 0.851 (0.801-0.899) | 164/262 (0.57-0.68) | ECE 0.126 / Brier 0.189 (n=150, mean conf 0.61, acc 0.73) |  | 0.0456 | 6.2 |

| config vs agent_mk | paired n | better | worse | tie |
|---|---|---|---|---|
| agent_vr | 150 | 3 | 30 | 117 |
| agent_pot | 150 | 4 | 8 | 138 |
| agent_sc | 150 | 2 | 8 | 140 |
| agent_cr | 150 | 5 | 1 | 144 |

**InsightBench 70 eval tasks, Lightning only, judge = Nemotron Super**

| config | n scored | summary judge mean | judge>=0.6 | judge None | insight ROUGE-1 | faithfulness | unsupported numbers | calibration (det) | attempts/item | $ total (system+judge) | s/item |
|---|---|---|---|---|---|---|---|---|---|---|---|
| agent_mk (post) | 70 | 0.370 (0.317-0.423) | 18/70 (0.17-0.37) | 0 | 0.181 (0.166-0.196) | 0.607 (0.547-0.663) | 7/1212 (0.00-0.01) | ECE 0.531 / Brier 0.483 (n=70, mean conf 0.76, acc 0.26) |  | 0.1164 | 16.0 |
| agent_vr (post) | 61 | 0.351 (0.295-0.407) | 14/61 (0.14-0.35) | 0 | 0.196 (0.180-0.213) | 0.621 (0.556-0.684) | 5/1404 (0.00-0.01) | ECE 0.545 / Brier 0.472 (n=61, mean conf 0.77, acc 0.23) | 1.25 | 0.2514 | 31.2 |
| agent_pot (v2) | 70 | 0.346 (0.300-0.396) | 13/70 (0.11-0.29) | 0 | 0.185 (0.169-0.200) | 0.567 (0.500-0.630) | 11/1250 (0.01-0.02) | ECE 0.600 / Brier 0.538 (n=70, mean conf 0.79, acc 0.19) |  | 0.1364 | 25.4 |
| agent_sc (v2) | 70 | 0.366 (0.313-0.423) | 16/70 (0.15-0.34) | 0 | 0.175 (0.160-0.191) | 0.620 (0.561-0.680) | 13/1084 (0.01-0.02) | ECE 0.214 / Brier 0.213 (n=70, mean conf 0.42, acc 0.23) |  | 0.1831 | 32.1 |
| agent_cr (v2) | 70 | 0.366 (0.309-0.424) | 19/70 (0.18-0.39) | 0 | 0.175 (0.160-0.190) | 0.704 (0.653-0.754) | 12/1259 (0.01-0.02) | ECE 0.313 / Brier 0.291 (n=70, mean conf 0.55, acc 0.27) |  | 0.1615 | 28.6 |

| config vs agent_mk | paired n | better | worse | tie |
|---|---|---|---|---|
| agent_vr | 61 | 14 | 19 | 28 |
| agent_pot | 70 | 21 | 21 | 28 |
| agent_sc | 70 | 24 | 20 | 26 |
| agent_cr | 70 | 23 | 22 | 25 |

Round spend (Nebius guard ledger): about $0.68 (cap $2.50), including the train calibration and judge calls.

## Caveats
- agent_cr is the only config ahead of agent_mk on TAT-QA: 110 vs 106 EM, 5 better and 1 worse when paired, ECE 0.126 vs 0.146. The Wilson CIs overlap, so this is not significant at n=150.
- PoT and self-consistency slightly hurt TAT-QA (8 worse each). The disagreements mostly change the scale/format of correct answers.
- InsightBench: all v2 configs are within noise of agent_mk on the judge mean. agent_cr has the best faithfulness (0.704 vs 0.607) and reaches >=0.6 on 19/70 vs 18/70. The judge is a single LLM (Nemotron Super), so its noise is comparable to the differences.
- The CR conf_map was fitted on 80 train items and is not monotone (small bins). Refit it on more train data before relying on it.
- The InsightBench "acc" used for ECE is judge>=0.6, so calibration there is coarse.
