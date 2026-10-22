"""Decision memo (Markdown). Only Claim-Gate-approved claims appear as findings."""
from __future__ import annotations


def render_memo(o: dict, run_id: str) -> str:
    a, q, c = o["analysis"], o["question"], o["confidence"]
    top = a["top_cause"]
    seg = (lambda d: ", ".join(f"{k}={v}" for k, v in d.items()) or "all segments")
    if top:
        share = top.get("raw_share_of_excess_late")
        why = (f"(estimated share of the excess late shipments vs the baseline late rate: {round(100*share)}%; above 100% means other segments improved)."
               if share is not None else "(broad rise across segments; no single segment explains it).")
        head = f"Top cause: **{a['top_cause_label']}** in {seg(top['segment'])} {why}"
    else:
        head = "No cause could be confirmed. Resolution: unresolved."
    L = [f"# Decision memo: why did on-time delivery drop? (run {run_id})", head, "",
         f"- Question: {q['query']}", f"- Baseline {q['baseline'][0]}..{q['baseline'][1]} vs period {q['period'][0]}..{q['period'][1]}",
         f"- Resolution: {o['resolution']}", f"- Data: SYNTHETIC labelled sample dataset", ""]
    if o.get("narrative"):
        L += ["## Summary (model-written, numbers checked by the Claim Gate)", o["narrative"], ""]
    L += ["## Findings (each verified by the Claim Gate)"]
    L += [f"- {cl['text']} Rows: {', '.join(cl['row_ids'])}" for cl in o["claims"]] or ["- none"]
    L += ["", "## Discarded alternatives"]
    L += [f"- Promotion {d['promo_id']}: dates overlap the period, but its shipments account for "
          f"{round(100*d['share_of_excess_late'])}% of the excess late shipments ({d['promo_late']} late of {d['promo_shipments']}). Refuted."
          for d in a["discarded"]] or ["- none"]
    if o["blocked_claims"]:
        L += ["", "## Blocked claims", *[f"- {b}" for b in o["blocked_claims"]]]
    L += ["", f"## Confidence: {c['confidence']}/100", f"- Formula: {c['formula']}; C={c['C']}, A={c['A']}, R={c['R']}; caps: {c['caps'] or 'none'}",
          "", "## Recommended actions"]
    L += [f"- Review the SLA performance of {top['segment'].get('carrier', 'the carrier')} in {top['segment'].get('region', 'the region')} and consider rerouting."] if top else ["- Collect more data; no cause confirmed."]
    L += ["", "## Limitations", "- Synthetic data." + (" Sample provider: deterministic rules, no language model." if not o.get("model_calls") else f" Model calls: {sum(c['ok'] for c in o['model_calls'])} ok, {sum(not c['ok'] for c in o['model_calls'])} fell back to deterministic rules."),
          f"- Evidence graph: {o['evidence_graph']['backend']}; Markovian status: {o['token_report']['markovian'].get('status')}.", ""]
    return "\n".join(L)
