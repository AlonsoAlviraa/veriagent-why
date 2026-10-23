"""verify-v2 tables: TAT-QA dev 150 and InsightBench 70 eval, baseline agent_mk / agent_vr (post) vs v2 configs,
plus paired wins/losses vs agent_mk on the same items. python -m bench.v2_tables"""
from __future__ import annotations
import json
from . import battery_tables as BT

BT.CONFIGS = ("agent_mk", "agent_vr", "agent_pot", "agent_sc", "agent_cr")


def paired(bench: str, key) -> str:
    ids = set(BT.SPLIT["eval"]) if bench == "insightbench" else None
    base = {r["id"]: key(r) for r in (BT.rows(f"{bench}-post-agent_mk", ids) or [])}
    L = []
    for s in ("agent_vr", "agent_pot", "agent_sc", "agent_cr"):
        r = BT.rows(f"{bench}-{'post' if s == 'agent_vr' else 'v2'}-{s}", ids) or []
        common = [x for x in r if x["id"] in base and key(x) is not None and base[x["id"]] is not None]
        w = sum(key(x) > base[x["id"]] for x in common)
        l = sum(key(x) < base[x["id"]] for x in common)
        L.append([s, len(common), w, l, len(common) - w - l])
    return BT.table(["config vs agent_mk", "paired n", "better", "worse", "tie"], L)


if __name__ == "__main__":
    em = lambda r: (r.get("scores") or {}).get("em")
    sj = lambda r: (r.get("scores") or {}).get("summary_judge")
    print(BT.tat(["post", "v2"], None, "TAT-QA dev n=150, Lightning only"))
    print("\n" + paired("tatqa", em))
    print("\n" + BT.ib(["post", "v2"], "InsightBench 70 eval tasks, Lightning only, judge = Nemotron Super"))
    print("\n" + paired("insightbench", sj))
