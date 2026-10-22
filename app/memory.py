"""Evidence graph on Meterless H-MEM, multi-round investigation on Meterless Markovian.

Every hypothesis, evidence node and support/refute edge is written to H-MEM (edges as records
with derivedFrom=[evidence, hypothesis] and a rel tag), so the H-MEM trust ledger is the audit
trail of the run. A local index mirrors ids for fast lookups. If node/the bridge is missing,
a local in-process fallback is used and logged as such.
"""
from __future__ import annotations
from .meterless import Bridge
from . import embeddings


def count_tokens(text: str) -> int:
    """Whitespace token count (approximation, labelled as such)."""
    return len(text.split())


class HMem:
    def __init__(self, bridge: Bridge | None):
        self.bridge = bridge
        self.backend = "meterless-hmem (vendored reference, via bridge)" if bridge else "local-fallback (node unavailable)"
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.mem_ids: dict[str, str] = {}
        self.pending: list = []
        self.real = bool(bridge) and embeddings.backend() != "hash"
        self.embedder = embeddings.model_name() if self.real else "hash-fnv1a-64 (vendored H-MEM mock)"
        self.embed_stats = {"embedded": 0, "failed": 0}

    def _write(self, key: str, content: str, source: str, tags: list[str], derived: list[str] | None = None) -> None:
        if self.bridge:
            self.pending.append((key, content[:500], source, tags, derived or []))
            if not self.real:
                self.flush()

    def flush(self) -> None:
        """Send buffered writes to H-MEM. With a real embedder, all pending contents are embedded in one
        batched call and each record carries its vector (H-MEM then ranks by real similarity)."""
        if not (self.bridge and self.pending):
            return
        batch, self.pending = self.pending, []
        vecs = [None] * len(batch)
        if self.real:
            try:
                vecs = embeddings.embed([b[1] for b in batch], "passage")
                self.embed_stats["embedded"] += len(batch)
            except Exception as e:
                self.embed_stats["failed"] += len(batch)
                self.embed_stats["last_error"] = type(e).__name__
        for (key, content, source, tags, derived), v in zip(batch, vecs):
            args = {"content": content, "source": source, "tags": tags,
                    "derivedFrom": [self.mem_ids[d] for d in derived if d in self.mem_ids]}
            if v is not None:
                args["embedding"] = v
            self.mem_ids[key] = self.bridge.call("hmem.add", **args)["id"]

    def add_node(self, nid: str, kind: str, source: str = "agent", **attrs) -> str:
        self.nodes[nid] = {"id": nid, "kind": kind, **attrs}
        self._write(nid, f"{kind} {nid}: {attrs.get('text', '')}", source, [kind, nid])
        return nid

    def add_edge(self, src: str, dst: str, rel: str, source: str = "evidence_evaluator") -> None:
        self.edges.append({"src": src, "dst": dst, "rel": rel})
        self._write(f"{src}->{dst}", f"{src} {rel} {dst}", source, ["edge", rel], [src, dst])

    def edges_to(self, dst: str, rel: str | None = None) -> list[dict]:
        return [e for e in self.edges if e["dst"] == dst and (rel is None or e["rel"] == rel)]

    def recall(self, query: str) -> str:
        if not self.bridge:
            return ""
        self.flush()
        args = {"query": query}
        if self.real:
            try:
                args["queryEmbedding"] = embeddings.embed([query], "query")[0]
            except Exception as e:
                self.embed_stats["last_error"] = type(e).__name__
        return self.bridge.call("hmem.query", **args)["context"]

    def ledger(self) -> dict:
        self.flush()
        return self.bridge.call("hmem.ledger") if self.bridge else {"entries": [], "stats": {}}
