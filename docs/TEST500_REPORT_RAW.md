Held-out `tatqa_test500_v1.json` n=500 (ids sha256 `02b8820dcc24918f…`)

| arm | repeats | EM per repeat | EM mean ± sd | EM majority | F1 mean | calls/item | unstable items | code_rev (dirty) |
|---|---|---|---|---|---|---|---|---|
| test500-agent_mk | 1 | [0.658] | 0.658 ± None | 0.658 | 0.745 | 2.45 | 0 | 74591af (False) |
| test500-rag | 1 | [0.528] | 0.528 ± None | 0.528 | 0.605 | 1.0 | 0 | 74591af (False) |

| A → B | ΔEM (B−A, per-item mean) | bootstrap 95% CI | McNemar p (majority) | B better / worse |
|---|---|---|---|---|
| test500-agent_mk → test500-rag | -0.130 | [-0.174, -0.086] | 0.0 | 32 / 97 |

| confidence | n rows | acc | mean conf | distinct values | Brier ↓ | ECE ↓ | AUROC ↑ | AURC ↓ |
|---|---|---|---|---|---|---|---|---|
| test500-agent_mk (shipped) | 500 | 0.658 | 0.973 | 6 | 0.3285 | 0.3267 | 0.5648 | 0.2878 |
| test500-rag (shipped) | 500 | 0.528 | 0.918 | 5 | 0.418 | 0.4216 | 0.6687 | 0.3579 |

| abstention (pre-registered: lex >= 0.809) | n | answered | coverage | selective EM | AURC ↓ |
|---|---|---|---|---|---|
| test500-agent_mk | 500 | 421 | 0.842 | 0.696 | 0.501 |
| test500-rag | 500 | 0 | 0.0 | None | 0.5261 |
