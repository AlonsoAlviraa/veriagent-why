# V8 research notes (sources only; no numbers that are not in the cited work)

| Source | What it says that matters for V8 |
|---|---|
| TAT-QA / TagOp, Zhu et al., ACL 2021 — https://aclanthology.org/2021.acl-long.254.pdf | Hybrid table+text QA; TagOp tags evidence cells/spans and applies a fixed set of aggregation operators instead of generating numbers; answer scale is predicted separately. Reported TagOp F1 58.0 vs human 90.8 (test). |
| TAT-LLM, Zhu et al., 2024 — https://arxiv.org/abs/2401.13223 (code: https://github.com/fengbinzhu/TAT-LLM) | Step-wise Extractor → Reasoner → Executor pipeline; the arithmetic is executed by an external executor rather than by the LLM. Basis for idea A (pointer + Python executor). |
| Program of Thoughts, Chen et al., 2022 — https://arxiv.org/abs/2211.12588 | Delegating computation to a program interpreter improves numeric QA; on TAT-QA dev the paper reports PoT+SC 70.2 vs CoT+SC 63.2 (few-shot, Codex). Basis for executing arithmetic in Python and for sampling + voting. |
| Self-consistency, Wang et al., 2022 — https://arxiv.org/abs/2203.11171 | Sample multiple reasoning paths at T>0 and take the majority answer; agreement is a natural confidence signal. Basis for idea B. |
| FINDER, EMNLP 2025 — https://aclanthology.org/2025.emnlp-main.1577/ | Financial hybrid QA with a generative retriever plus PoT and dynamically chosen in-context examples (not used in V8 round 1; candidate for later rounds). |

Discarded for V8 (per Code Reviewer + V7.1 ablation): more regex fixes, an LLM critic, forced literal-only scale (V7.1 arm C: −18 EM), structured-output rewrite (V7.1 f1: −11.3 EM).
