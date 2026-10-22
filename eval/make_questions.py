"""Writes eval/questions.json (24 questions: 6 dev, 18 test) and eval/SPLITS.sha256.
Each question has its own seeded synthetic dataset (eval/build_datasets.py). The demo scenario
(seed 42) is NOT in any split. Trap types promotion_effect and seasonality are test-only.
Run once; the test split is frozen by its hash and must not be edited after the first test run."""
import hashlib, json
from pathlib import Path

E = Path(__file__).parent
B, P = ["2026-09-15", "2026-09-30"], ["2026-10-01", "2026-10-14"]
Q = "Why did on-time delivery drop between 2026-10-01 and 2026-10-14 compared with 2026-09-15 to 2026-09-30?"


def breach(c, r, p=0.5): return {"breach": {"carrier": c, "region": r, "p": p}}


SPEC = [  # (split, kind, scenario, expected label)
    ("dev", "carrier_breach", breach("CarrierA", "East"), "carrier_sla_breach"),
    ("dev", "carrier_breach", breach("CarrierC", "West", 0.45), "carrier_sla_breach"),
    ("dev", "carrier_breach", breach("CarrierB", "South", 0.6), "carrier_sla_breach"),
    ("dev", "breach_with_date_promo_trap", {**breach("CarrierA", "West"), "promo": {"category": "beauty", "region": "East", "causes_late": False}}, "carrier_sla_breach"),
    ("dev", "negative_control", {}, "none"),
    ("dev", "carrier_breach", breach("CarrierC", "North", 0.4), "carrier_sla_breach"),
    ("test", "carrier_breach", breach("CarrierA", "North"), "carrier_sla_breach"),
    ("test", "carrier_breach", breach("CarrierB", "East", 0.45), "carrier_sla_breach"),
    ("test", "carrier_breach", breach("CarrierC", "South", 0.55), "carrier_sla_breach"),
    ("test", "carrier_breach", breach("CarrierA", "South", 0.4), "carrier_sla_breach"),
    ("test", "carrier_breach", breach("CarrierB", "West", 0.5), "carrier_sla_breach"),
    ("test", "carrier_breach", breach("CarrierC", "East", 0.35), "carrier_sla_breach"),
    ("test", "breach_with_date_promo_trap", {**breach("CarrierC", "West"), "promo": {"category": "apparel", "region": "North", "causes_late": False}}, "carrier_sla_breach"),
    ("test", "breach_with_date_promo_trap", {**breach("CarrierA", "East"), "promo": {"category": "electronics", "region": "South", "causes_late": False}}, "carrier_sla_breach"),
    ("test", "breach_with_date_promo_trap", {**breach("CarrierB", "South"), "promo": {"category": "home", "region": "West", "causes_late": False}}, "carrier_sla_breach"),
    ("test", "seasonality", {"seasonal_p": 0.25}, "seasonality"),
    ("test", "seasonality", {"seasonal_p": 0.2}, "seasonality"),
    ("test", "seasonality", {"seasonal_p": 0.3}, "seasonality"),
    ("test", "promotion_effect", {"promo": {"category": "electronics", "region": "North", "causes_late": True}}, "promotion_effect"),
    ("test", "promotion_effect", {"promo": {"category": "apparel", "region": "East", "causes_late": True}}, "promotion_effect"),
    ("test", "promotion_effect", {"promo": {"category": "beauty", "region": "West", "causes_late": True}}, "promotion_effect"),
    ("test", "negative_control", {}, "none"),
    ("test", "negative_control", {"promo": {"category": "home", "region": "North", "causes_late": False}}, "none"),
    ("test", "negative_control", {}, "none"),
]

qs = [{"qid": f"q{i+1:02d}", "split": sp, "kind": k, "seed": 1001 + i, "scenario": sc, "expected_label": lab,
       "input": {"query": Q, "kpi": "on_time_rate", "baseline": B, "period": P, "dataset": f"q{i+1:02d}"}}
      for i, (sp, k, sc, lab) in enumerate(SPEC)]
assert sum(q["split"] == "test" for q in qs) == 18 and len(qs) == 24
(E / "questions.json").write_text(json.dumps(qs, indent=2) + "\n")
test = json.dumps([q for q in qs if q["split"] == "test"], sort_keys=True).encode()
(E / "SPLITS.sha256").write_text(hashlib.sha256(test).hexdigest() + "  test split of eval/questions.json\n")
print("written", len(qs))
