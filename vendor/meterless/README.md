# Vendored: Meterless engine reference implementations (Apache-2.0)

Copies of the open-source Meterless reference engines, used by `meterless_bridge/`:
- `hmem/` = `engines/hmem/reference/src`
- `markovian/` = `engines/markovian/reference/src`

Source: https://github.com/Meterless/Meterless at commit `1742dec56a66e58eef9dda2d2b865823758ca8cd` (fetched 22 Oct 2026).
Licence: Apache License 2.0, see `LICENSE`. Pre-existing open-source library, not written for this submission.

## Local modifications (declared)
Only `hmem/embeddings.ts` is changed, in two small places marked `VeriAgent Why local change`:
1. `setEmbedOverride(fn)`: an optional hook so the bridge can supply real embedding vectors (NVIDIA, computed in Python) through the same `embed(text) -> number[]` contract the file documents. With no override, the original FNV-1a hash embedder runs unchanged.
2. `cosine()` returns 0 when vector lengths differ, so a hash vector is never compared with a real one.
Everything else is byte-identical to the upstream commit above.
