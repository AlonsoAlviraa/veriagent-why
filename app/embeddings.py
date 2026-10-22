"""Embedder with the same provider switch as app/llm.py.

- sample (SAMPLE_MODE / LLM_PROVIDER=sample): deterministic offline hash embedder, a Python port of the
  vendored Meterless H-MEM mock (FNV-1a per token into 64 dims, L2-normalised). No network; CI-safe.
- nvidia: NVIDIA free endpoint POST {NVIDIA_BASE_URL}/embeddings, model EMBED_MODEL
  (default nvidia/nemotron-3-embed-1b, 2048 dims, verified on the free API on 22 Oct 2026),
  input_type query|passage. Paced and retried through llm._post. NVIDIA_API_KEY from env only.
- nightshift: the Meterless Nightshift contract has no documented embeddings route yet, so embeddings go
  to NVIDIA when NVIDIA_API_KEY is set, else the hash embedder. Declared in docs.
Passage vectors are cached on disk (data/emb_cache/, gitignored) keyed by sha256(model|type|text).
Every vector is L2-normalised so cosine = dot product.
"""
from __future__ import annotations
import hashlib, json, math, re, urllib.request
from .config import ROOT, env, provider

HASH_DIM = 64
CACHE = ROOT / "data" / "emb_cache"
STATS = {"calls": 0, "texts": 0, "cache_hits": 0, "tokens": 0, "errors": 0}


def model_name() -> str:
    return "hash-fnv1a-64" if backend() == "hash" else env("EMBED_MODEL", "nvidia/nemotron-3-embed-1b")


def backend() -> str:
    p = provider()
    if p == "sample":
        return "hash"
    if p in ("nvidia", "nightshift") and env("NVIDIA_API_KEY") and env("EMBED_PROVIDER", "nvidia") != "hash":
        return "nvidia"
    return "hash"


def _fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def hash_embed(text: str) -> list[float]:
    vec = [0.0] * HASH_DIM
    for t in [t for t in re.sub(r"[^a-z0-9\s]", " ", text.lower()).split() if len(t) > 1]:
        h = _fnv1a(t)
        vec[h % HASH_DIM] += (1 if (h >> 8) % 2 == 0 else -1) * (1 + ((h >> 16) % 8) / 8)
    return _norm(vec)


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return 0.0 if len(a) != len(b) else sum(x * y for x, y in zip(a, b))


def _key(model: str, kind: str, text: str) -> str:
    return hashlib.sha256(f"{model}|{kind}|{text}".encode()).hexdigest()


def _remote(texts: list[str], kind: str, model: str) -> list[list[float]]:
    from . import llm
    base = env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    body = {"model": model, "input": texts, "input_type": kind, "encoding_format": "float", "truncate": "END"}
    req = urllib.request.Request(base.rstrip("/") + "/embeddings", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {env('NVIDIA_API_KEY')}"})
    out = llm._post(req, 60, "nvidia")
    STATS["calls"] += 1
    STATS["tokens"] += (out.get("usage") or {}).get("total_tokens", 0)
    data = sorted(out["data"], key=lambda d: d.get("index", 0))
    if len(data) != len(texts):
        raise ValueError("embedding count mismatch")
    return [_norm(d["embedding"]) for d in data]


def embed(texts: list[str], kind: str = "passage", batch: int = 64) -> list[list[float]]:
    """kind: 'query' or 'passage'. Live failures raise; callers fall back (and say so in the trace)."""
    if kind not in ("query", "passage"):
        raise ValueError("kind must be query or passage")
    if backend() == "hash":
        return [hash_embed(t) for t in texts]
    model = model_name()
    out: list = [None] * len(texts)
    todo = []
    for i, t in enumerate(texts):
        f = CACHE / (_key(model, kind, t) + ".json")
        if kind == "passage" and f.exists():
            out[i] = json.loads(f.read_text()); STATS["cache_hits"] += 1
        else:
            todo.append(i)
    for s in range(0, len(todo), batch):
        idx = todo[s:s + batch]
        try:
            vecs = _remote([texts[i] or " " for i in idx], kind, model)
        except Exception:
            STATS["errors"] += 1
            raise
        STATS["texts"] += len(idx)
        for i, v in zip(idx, vecs):
            out[i] = v
            if kind == "passage":
                CACHE.mkdir(parents=True, exist_ok=True)
                (CACHE / (_key(model, kind, texts[i]) + ".json")).write_text(json.dumps([round(x, 6) for x in v]))
    return out
