"""Held-out test set v2 (18 questions), written 22 Oct 2026 BEFORE any robustness tuning, with new seeds
(5001+) and the noisy generator variant. RESERVED for the final Nemotron eval: no agent or baseline run
on it until then (eval.py refuses without --final-v2). Frozen by sha256 in eval/SPLITS_test_v2.sha256."""
import hashlib, json
from pathlib import Path
from make_questions import N, breach, Q, B, P, secondary, primary_segment

E = Path(__file__).parent
SPEC = [
    ("noisy_breach", {**breach("CarrierB", "North", 0.38), "noise": N(static=("CarrierA", "South"))}, "carrier_sla_breach"),
    ("noisy_breach", {**breach("CarrierA", "West", 0.33), "noise": N(bump=("CarrierC", "North", 0.13), drop=0.5)}, "carrier_sla_breach"),
    ("noisy_breach", {**breach("CarrierC", "South", 0.42), "noise": N(static=("CarrierB", "East"), bump=("CarrierA", "North", 0.12))}, "carrier_sla_breach"),
    ("multi_cause", {**breach("CarrierC", "West", 0.48), "noise": N(breach2=("CarrierB", "North", 0.24))}, "carrier_sla_breach"),
    ("multi_cause", {**breach("CarrierB", "South", 0.44), "noise": N(breach2=("CarrierA", "East", 0.26))}, "carrier_sla_breach"),
    ("multi_cause", {**breach("CarrierA", "East", 0.5), "noise": N(breach2=("CarrierC", "North", 0.2), static=("CarrierB", "West"))}, "carrier_sla_breach"),
    ("noisy_breach_with_date_promo_trap", {**breach("CarrierA", "South", 0.45), "promo": {"category": "home", "region": "North", "causes_late": False}, "noise": N()}, "carrier_sla_breach"),
    ("noisy_breach_with_date_promo_trap", {**breach("CarrierB", "West", 0.4), "promo": {"category": "electronics", "region": "East", "causes_late": False}, "noise": N(drop=0.5)}, "carrier_sla_breach"),
    ("noisy_promotion_effect", {"promo": {"category": "apparel", "region": "South", "causes_late": True}, "noise": N()}, "promotion_effect"),
    ("noisy_promotion_effect", {"promo": {"category": "home", "region": "East", "causes_late": True}, "noise": N(static=("CarrierC", "North"))}, "promotion_effect"),
    ("noisy_promotion_effect", {"promo": {"category": "electronics", "region": "West", "causes_late": True}, "noise": N(bump=("CarrierB", "South", 0.12))}, "promotion_effect"),
    ("noisy_seasonality", {"seasonal_p": 0.21, "noise": N()}, "seasonality"),
    ("noisy_seasonality", {"seasonal_p": 0.27, "noise": N(drop=0.5)}, "seasonality"),
    ("noisy_seasonality", {"seasonal_p": 0.18, "noise": N(static=("CarrierA", "North"))}, "seasonality"),
    ("noisy_negative_distractor", {"noise": N(static=("CarrierC", "South"))}, "none"),
    ("noisy_negative_distractor", {"noise": N(bump=("CarrierB", "North", 0.11))}, "none"),
    ("noisy_negative_partial_data", {"noise": N(drop=0.7)}, "none"),
    ("noisy_negative_promo_no_effect", {"promo": {"category": "beauty", "region": "South", "causes_late": False}, "noise": N()}, "none"),
]
qs = [{"qid": f"t2_{i+1:02d}", "split": "test_v2", "kind": k, "seed": 5001 + i, "scenario": sc, "expected_label": lab,
       "expected_segment": primary_segment(sc), "expected_secondary": secondary(sc),
       "input": {"query": Q, "kpi": "on_time_rate", "baseline": B, "period": P, "dataset": f"t2_{i+1:02d}"}}
      for i, (k, sc, lab) in enumerate(SPEC)]
assert len(qs) == 18
(E / "questions_test_v2.json").write_text(json.dumps(qs, indent=2) + "\n")
(E / "SPLITS_test_v2.sha256").write_text(hashlib.sha256(json.dumps(qs, sort_keys=True).encode()).hexdigest() + "  eval/questions_test_v2.json (reserved for the final Nemotron eval)\n")
print("written", len(qs))
