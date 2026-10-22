"""Evidence graph on Meterless H-MEM, multi-round investigation on Meterless Markovian.

Every hypothesis, evidence node and support/refute edge is written to H-MEM (edges as records
with derivedFrom=[evidence, hypothesis] and a rel tag), so the H-MEM trust ledger is the audit
trail of the run. A local index mirrors ids for fast lookups. If node/the bridge is missing,
a local in-process fallback is used and logged as such.
"""
from __future__ import annotations
from .meterless import Bridge


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

    def _write(self, key: str, content: str, source: str, tags: list[str], derived: list[str] | None = None) -> None:
        if self.bridge:
            r = self.bridge.call("hmem.add", content=content[:500], source=source, tags=tags,
                                 derivedFrom=[self.mem_ids[d] for d in derived or [] if d in self.mem_ids])
            self.mem_ids[key] = r["id"]

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
        return self.bridge.call("hmem.query", query=query)["context"] if self.bridge else ""

    def ledger(self) -> dict:
        return self.bridge.call("hmem.ledger") if self.bridge else {"entries": [], "stats": {}}
