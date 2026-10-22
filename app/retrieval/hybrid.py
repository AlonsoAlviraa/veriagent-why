"""Hybrid retrieval over row text: BM25 + dense embeddings fused with reciprocal-rank fusion (RRF).
Rows keep their row ids so every hit can be cited and clicked through."""
from __future__ import annotations
from ..bm25 import bm25
from .. import embeddings

RRF_K = 60


def rrf(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal-rank fusion: score(d) = sum over rankings of 1 / (k + rank), rank from 1."""
    out: dict[str, float] = {}
    for r in rankings:
        for i, d in enumerate(r):
            out[d] = out.get(d, 0.0) + 1.0 / (k + i + 1)
    return out


def search(rows: list[dict], query: str, id_key: str, text_key: str = "text", top_k: int = 30) -> tuple[list[dict], dict]:
    """Returns (top rows with bm25/dense/rrf scores, meta). Dense falls back to BM25-only on embedder failure."""
    if not rows:
        return [], {"dense": "skipped (no rows)", "embed_model": embeddings.model_name()}
    ids = [str(r[id_key]) for r in rows]
    texts = [str(r.get(text_key) or "") for r in rows]
    bs = bm25(texts, query)
    bm_rank = [ids[i] for i in sorted(range(len(ids)), key=lambda i: (-bs[i], ids[i])) if bs[i] > 0]
    meta = {"embed_model": embeddings.model_name(), "embed_backend": embeddings.backend()}
    ds = None
    try:
        qv = embeddings.embed([query], "query")[0]
        pv = embeddings.embed(texts, "passage")
        ds = [embeddings.cosine(qv, v) for v in pv]
        dense_rank = [ids[i] for i in sorted(range(len(ids)), key=lambda i: (-ds[i], ids[i])) if ds[i] > 0]
        meta["dense"] = "ok"
    except Exception as e:
        dense_rank = []
        meta["dense"] = f"failed, BM25 only ({type(e).__name__})"
    fused = rrf([bm_rank, dense_rank] if dense_rank else [bm_rank])
    order = sorted(fused, key=lambda d: (-fused[d], d))[:top_k]
    pos = {d: i for i, d in enumerate(ids)}
    hits = []
    for d in order:
        i = pos[d]
        hits.append({**rows[i], "bm25": round(bs[i], 4), "dense": None if ds is None else round(ds[i], 4), "rrf": round(fused[d], 5)})
    meta.update({"candidates": len(rows), "returned": len(hits)})
    return hits, meta
