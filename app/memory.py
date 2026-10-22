"""Evidence graph + Markovian-style token report.

Interface mirrors what the Meterless engines provide (H-MEM: graph nodes/edges + audit
ledger; Markovian: projected-vs-actual token report). Day-1 status: in-process LOCAL
implementation, NOT Meterless yet. TODO(Day 2-3): bind HMem/Markovian to the open-source
Meterless engines (github.com/Meterless/Meterless) via the Node bridge.
"""
from __future__ import annotations


class HMem:
    backend = "local-inprocess (TODO: Meterless H-MEM)"

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.ledger: list[dict] = []

    def add_node(self, nid: str, kind: str, **attrs) -> str:
        self.nodes[nid] = {"id": nid, "kind": kind, **attrs}
        self.ledger.append({"op": "node", "id": nid, "kind": kind})
        return nid

    def add_edge(self, src: str, dst: str, rel: str, **attrs) -> None:
        self.edges.append({"src": src, "dst": dst, "rel": rel, **attrs})
        self.ledger.append({"op": "edge", "src": src, "dst": dst, "rel": rel})

    def edges_to(self, dst: str, rel: str | None = None) -> list[dict]:
        return [e for e in self.edges if e["dst"] == dst and (rel is None or e["rel"] == rel)]


def count_tokens(text: str) -> int:
    """Whitespace token count (an approximation, stated as such in reports)."""
    return len(text.split())


class Markovian:
    backend = "local-inprocess (TODO: Meterless Markovian)"

    def __init__(self):
        self.rounds: list[dict] = []

    def record(self, round_no: int, projected: int, actual: int) -> None:
        self.rounds.append({"round": round_no, "projected_tokens": projected, "actual_tokens": actual})

    def report(self) -> dict:
        p = sum(r["projected_tokens"] for r in self.rounds)
        a = sum(r["actual_tokens"] for r in self.rounds)
        return {"backend": self.backend, "token_unit": "whitespace tokens (approx.)", "rounds": self.rounds,
                "projected_total": p, "actual_total": a, "avoided_by_s1": p - a}
