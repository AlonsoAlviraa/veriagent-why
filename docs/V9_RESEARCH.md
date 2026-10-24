# V9 research: which recent ideas fit VeriAgent Why, and which we drop

Scope: papers 2022-2026 relevant to (a) answer accuracy on hybrid table+text financial QA (TAT-QA) and (b) confidence /
selective answering. Reading depth is disclosed per paper: **[F]** full text or method sections read, **[A]** abstract and
search excerpts only (an arXiv fetch timed out during this session). Numbers quoted are the papers' own; none are ours.

## What V7.1 and V8 already taught us (binding constraints)
* **Answer-format changes are rejected and are not retried** (V7.1: structured output / scale rules; V8: pointer/PoT answer arms
  lost 7-18 EM points — systematic pointer errors on spans and scales). V9 does not change the answer format.
* What *worked* in V8 was **confidence only**: pointer-agreement features gave hold-out AUROC 0.634 vs frozen lex 0.532, at ~3.1x
  V7's cost. So the open problem is: *equal or better ranking at much lower cost*, and better calibration.
* Our error mix on test500 (from earlier audits): ~54% span-boundary, ~17% numeric, ~28% reasoning. Span-boundary errors are hard to
  detect from the answer string alone, so signals that read the model's own uncertainty (token probabilities, disagreement across
  samples, a verifier reading the evidence) are the natural candidates.
* Code Reviewer notes: GroupKFold by table; pointer-as-verifier acceptable only on a fresh slice. Both adopted.
* Probe (this session): Nebius returns token `logprobs` with `top_logprobs` for our model (the sampled token is repeated in the
  top list; we de-duplicate). This makes sample-free signals possible at ~0 extra calls.

## Candidate papers

| # | Paper | Core idea | Evidence (paper's) | Extra cost/item | Fit / expected gain on our errors | Risk |
|---|---|---|---|---|---|---|
| 1 | Farquhar, Kossen, Kuhn, Gal. *Detecting hallucinations in LLMs using semantic entropy*, Nature 630 (2024). https://www.nature.com/articles/s41586-024-07421-0 [F] | Sample several answers, cluster by meaning, entropy over clusters. | AUROC 0.790 vs P(True) 0.698 and naive entropy 0.691, averaged over 30 task×model settings. | K calls | High: our answers are short and clusterable deterministically (normalised number/span key + scale) — no NLI model needed. Targets numeric and reasoning errors. | Low diversity at T=0.7 on a strong model → many single-cluster items (ties). |
| 2 | Vashurin et al. *Benchmarking UQ methods for LLMs with LM-Polygraph*, TACL 2025. arXiv:2406.15627 [A] | Benchmark of white-box/black-box UQ; simple information-based scores (MSP, mean token entropy) are strong baselines for short answers. | Reported as competitive on short-form QA. | 0 | High: free given logprobs; answer-token probability should flag uncertain span boundaries. | JSON wrapper tokens dilute the score — we restrict to answer-value tokens. |
| 3 | Fadeeva et al. *Fact-checking the output of LLMs via token-level uncertainty quantification (CCP)*, Findings ACL 2024. arXiv:2403.04696 [A] | Claim-conditioned token probability: only tokens that carry the claim matter. | Gains over plain token probability on claim-level detection. | 0 | Medium-high; we implement the cheap version (answer-token span, min prob, top1-top2 margin). Full CCP needs an NLI model — dropped. | Partial implementation. |
| 4 | Kadavath et al. *Language Models (Mostly) Know What They Know*, arXiv:2207.05221 (2022) [F] | P(True): ask the model whether a proposed answer is true; read the probability of "True". | Well calibrated for large models, better with evidence/samples in context. | 1 | High: an evidence-conditioned verifier of the *final* answer can catch reasoning and scale errors that lex cannot see. | Self-preference bias (verifier = same model). |
| 5 | Tian et al. *Just Ask for Calibration*, EMNLP 2023. arXiv:2305.14975 [A] | Verbalized confidence from RLHF models can be better calibrated than token probs. | Mixed across models. | 0 (same call as #4) | Medium; logged as a feature, not trusted alone. | Overconfidence (see #6). |
| 6 | Xiong et al. *Can LLMs Express Their Uncertainty?*, ICLR 2024. arXiv:2306.13063 [A] | Systematic study of verbalized/sampling/aggregation confidence. | Verbalized alone is overconfident; consistency-based helps. | — | Motivates combining signals; argues against verbalized-only. | — |
| 7 | Vashurin et al. *CoCoA: uncertainty from confidence + consistency*, arXiv:2502.04964 (2025) [A] | Combine model confidence with semantic consistency across samples. | Improves over either part. | K | High, and it is what our logistic V9_full does (lex + logprob + P(True) + agreement). | Overfitting the combiner — mitigated by GroupKFold. |
| 8 | Yadkori et al. *Mitigating LLM Hallucinations via Conformal Abstention*, arXiv:2405.01563 (2024) [A]; Angelopoulos et al. *Conformal Risk Control*, ICLR 2024 [A] | Choose the abstention threshold so that a risk is bounded with a finite-sample guarantee. | Guaranteed risk under exchangeability. | 0 (offline) | Medium: does not improve ranking but gives an honest operating point instead of a hand-picked 0.809. | Exchangeability only within the slice; train vs test shift. |
| 9 | Huang et al. *LLMs Cannot Self-Correct Reasoning Yet*, ICLR 2024. arXiv:2310.01798 [A]; Kamoi et al. *When Can LLMs Actually Correct Their Own Mistakes?*, TACL 2024 [A] | Intrinsic self-correction without external feedback does not help, often hurts. | Negative results. | — | Rules out "ask the model to fix itself" answer arms. | — |
| 10 | Chen et al. *Program of Thoughts*, TMLR 2023. arXiv:2211.12588 [F] | Code generation for numeric reasoning; PoT+SC beats CoT+SC (~7% on TAT-QA); SC less impactful on financial data. | As stated. | — | Already tried in spirit (V8 pointer) → answer arms lost. Dropped. | — |
| 11 | Toh et al. *PROVE: verifying program outputs*, arXiv:2410.12608 (2024) [A] | Verify a CoT answer by generating and executing a program; keep agreeing answers. | Gains on math benchmarks. | 2-6 | Overlaps V8 pointer verifier (systematic errors on TAT-QA spans). Dropped for answers; its confidence analogue = V8_refit baseline. | Same as V8. |
| 12 | Zhu et al. *TAT-LLM*, arXiv:2401.13223 (2024) [A]; Zhu et al. *TAT-QA*, ACL 2021, arXiv:2105.07624 [F] | Step-wise extractor→reasoner→executor pipeline, fine-tuned. | Strong TAT-QA results with fine-tuning. | — | Needs fine-tuning (out of scope, no training budget). | — |
| 13 | Srivastava et al. *Evaluating LLMs' mathematical reasoning in financial document QA*, arXiv:2402.11194 (2024) [A] | Analysis of LLM failure modes on TAT-QA/FinQA; proposes EEDP prompting. | Error analysis: extraction and multi-step arithmetic dominate. | 0-1 | Confirms our error mix; EEDP is a prompt-format change → excluded by the V7.1 rule. | — |
| 14 | FINDER (financial retrieval-augmented QA), EMNLP 2025 [A] | Retriever fine-tuning + reranking for financial documents. | Retrieval gains. | training | TAT-QA gives the gold table/paragraphs already; retrieval is not our bottleneck here. Dropped. | — |
| 15 | Gold-guided programmatic distillation for hybrid QA, arXiv:2607.14709 (2026) [A] | Distil gold programs into a small model. | 87.00 EM on TAT-QA (paper's). | fine-tuning | Requires training; out of scope. Dropped. | — |

## Ranking and choice (top 4 implemented)
1. **I1 — token log-prob confidence** (#2, #3): free, white-box, directly aimed at span-boundary uncertainty. Highest value/cost.
2. **I2 — P(True) evidence-conditioned verifier + verbalized confidence** (#4, #5, #6): one short call; sees the evidence and the final answer.
3. **I3 — semantic entropy / self-consistency over V7's exact final prompt** (#1, #7): strongest published detector; K=3 to bound cost.
   **I3b** is the only answer-changing arm (majority vote, V7 wins ties) and is judged by the strict answer rule.
4. **I4 — conformal risk control** for the abstention threshold (#8): offline, gives a guaranteed operating point.

Combiner: logistic over [lex, I1, I2] (*V9_cheap*, +1 call) and [lex, I1, I2, I3, V8 features] (*V9_full*), out-of-fold with
GroupKFold by table. Baselines on the same items: lex frozen, lex Platt, V8 refit.

## Dropped, and why
PoT / pointer answer replacement and PROVE-style program verification (V8 showed systematic pointer errors); structured output,
scale rules and EEDP-style prompt formats (V7.1 rejection rule); intrinsic self-correction (#9, negative evidence);
fine-tuning approaches TAT-LLM / distillation / FINDER (no training budget, and retrieval is not our bottleneck on TAT-QA);
verbalized-only confidence (#6, overconfident); full CCP with NLI (extra model, small expected gain over the answer-token version).
