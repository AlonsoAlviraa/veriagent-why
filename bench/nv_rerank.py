"""NVIDIA reranker as a decision input (relevance gate + citation-support signal) for the Markovian control.

Model: nvidia/llama-nemotron-rerank-vl-1b-v2 on build.nvidia.com (free endpoint, NVIDIA_API_KEY, never logged).
Verified 2026-10-23: llama-nemotron-rerank-1b-v2, llama-3.2-nemoretriever-500m-rerank-v2 and
llama-3.2-nv-rerankqa-1b-v2 return HTTP 410 (end of life), so they are not used.
Free tier pacing: <= 35 requests/min client-side (limit 40). Output: raw logits -> sigmoid -> p in (0,1)
(\"calibrated-ish\": sigmoid of a cross-encoder logit, not a fitted probability).
"""
from __future__ import annotations
import json, math, os, threading, time, urllib.request

MODEL = "nvidia/llama-nemotron-rerank-vl-1b-v2"
URL = "https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-nemotron-rerank-vl-1b-v2/reranking"
MIN_INTERVAL = 60.0 / 35
_lock, _last = threading.Lock(), [0.0]
STATS = {"calls": 0, "seconds": 0.0, "errors": 0}


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def rank(query: str, passages: list[str], timeout: float = 30) -> list[float]:
    """p(relevant) per passage, in input order. Raises on failure (callers treat as 'no signal')."""
    if not passages:
        return []
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        raise RuntimeError("NVIDIA_API_KEY not set")
    body = {"model": MODEL, "query": {"text": query[:4000]}, "passages": [{"text": (p or " ")[:6000]} for p in passages], "truncate": "END"}
    for attempt in range(3):
        with _lock:
            w = _last[0] + MIN_INTERVAL - time.time()
            if w > 0:
                time.sleep(w)
            _last[0] = time.time()
        t = time.time()
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.load(r)
            STATS["calls"] += 1
            STATS["seconds"] += time.time() - t
            p = [0.0] * len(passages)
            for x in out["rankings"]:
                p[x["index"]] = round(sigmoid(float(x["logit"])), 5)
            return p
        except urllib.error.HTTPError as e:
            STATS["errors"] += 1
            if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
