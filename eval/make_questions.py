"""Writes eval/questions.json (40 questions: 22 dev, 18 test [contaminated, see RESULTS_HISTORY]; dev cases were added over time) and eval/SPLITS.sha256.
Each question has its own seeded synthetic dataset (eval/build_datasets.py). The demo scenario
(seed 42) is NOT in any split. Trap types promotion_effect and seasonality are test-only.
Run once; the test split is frozen by its hash and must not be edited after the first test run."""
import hashlib, json
from pathlib import Path

E = Path(__file__).parent
B, P = ["2026-09-15", "2026-09-30"], ["2026-10-01", "2026-10-14"]
Q = "Why did on-time delivery drop between 2026-10-01 and 2026-10-14 compared with 2026-09-15 to 2026-09-30?"


def N(static=None, bump=None, breach2=None, drop=0.3):
    """Noisy variant: per-carrier base rates, daily variance, volume noise, partial tickets/returns, distractors."""
    n = {"drop_tickets": drop, "drop_returns": drop}
    if static: n["distractor_static"] = {"cell": list(static), "p": 0.22}
    if bump: n["distractor_bump"] = {"cell": list(bump[:2]), "p": bump[2]}
    if breach2: n["breach2"] = {"carrier": breach2[0], "region": breach2[1], "p": breach2[2]}
    return n


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
    # Added 22 Oct after the first test run: dev-only examples of the two test-only trap families,
    # so the new seasonality / promotion-vs-carrier logic is tuned on dev only. Test split unchanged.
    ("dev", "seasonality", {"seasonal_p": 0.22}, "seasonality"),
    ("dev", "seasonality", {"seasonal_p": 0.28}, "seasonality"),
    ("dev", "promotion_effect", {"promo": {"category": "home", "region": "South", "causes_late": True}}, "promotion_effect"),
    ("dev", "promotion_effect", {"promo": {"category": "electronics", "region": "West", "causes_late": True}}, "promotion_effect"),
    # Added 22 Oct: NOISY dev cases (noisy generator variant) for robustness tuning; dev only.
    ("dev", "noisy_breach", {**breach("CarrierA", "South", 0.4), "noise": N(static=("CarrierC", "East"))}, "carrier_sla_breach"),
    ("dev", "noisy_breach", {**breach("CarrierC", "North", 0.35), "noise": N(bump=("CarrierB", "West", 0.14))}, "carrier_sla_breach"),
    ("dev", "multi_cause", {**breach("CarrierB", "East", 0.5), "noise": N(breach2=("CarrierA", "West", 0.25))}, "carrier_sla_breach"),
    ("dev", "multi_cause", {**breach("CarrierA", "North", 0.45), "noise": N(breach2=("CarrierC", "South", 0.22))}, "carrier_sla_breach"),
    ("dev", "noisy_breach_with_date_promo_trap", {**breach("CarrierC", "East", 0.45), "promo": {"category": "apparel", "region": "West", "causes_late": False}, "noise": N()}, "carrier_sla_breach"),
    ("dev", "noisy_negative_distractor", {"noise": N(static=("CarrierB", "South"), bump=("CarrierA", "East", 0.1))}, "none"),
    ("dev", "noisy_seasonality", {"seasonal_p": 0.24, "noise": N()}, "seasonality"),
    ("dev", "noisy_promotion_effect", {"promo": {"category": "beauty", "region": "North", "causes_late": True}, "noise": N(static=("CarrierA", "West"))}, "promotion_effect"),
    # Added 22 Oct: HARDER dev cases (weak signal, heavy missing data, close multi-cause, breach inside a broad rise).
    ("dev", "weak_noisy_breach", {**breach("CarrierB", "West", 0.22), "noise": N(drop=0.6)}, "carrier_sla_breach"),
    ("dev", "close_multi_cause", {**breach("CarrierC", "East", 0.4), "noise": N(breach2=("CarrierA", "South", 0.34))}, "carrier_sla_breach"),
    ("dev", "breach_inside_broad_rise", {**breach("CarrierA", "West", 0.55), "seasonal_p": None, "noise": N(bump=("CarrierB", "North", 0.15))}, "carrier_sla_breach"),
    ("dev", "noisy_negative_heavy_missing", {"noise": N(drop=0.8, static=("CarrierC", "West"))}, "none"),
]

def secondary(sc):
    b2 = (sc.get("noise") or {}).get("breach2")
    return {"label": "carrier_sla_breach", "segment": {"carrier": b2["carrier"], "region": b2["region"]}} if b2 else None


def primary_segment(sc):
    return {"carrier": sc["breach"]["carrier"], "region": sc["breach"]["region"]} if sc.get("breach") else None


def main():
    qs = [{"qid": f"q{i+1:02d}", "split": sp, "kind": k, "seed": 1001 + i, "scenario": sc, "expected_label": lab,
           "expected_segment": primary_segment(sc), "expected_secondary": secondary(sc),
           "input": {"query": Q, "kpi": "on_time_rate", "baseline": B, "period": P, "dataset": f"q{i+1:02d}"}}
          for i, (sp, k, sc, lab) in enumerate(SPEC)]
    for q in qs:  # keep the frozen test split byte-identical to its original form
        if q["split"] == "test":
            q.pop("expected_segment"); q.pop("expected_secondary")
    assert sum(q["split"] == "test" for q in qs) == 18 and len(qs) == 40
    (E / "questions.json").write_text(json.dumps(qs, indent=2) + "\n")
    test = json.dumps([q for q in qs if q["split"] == "test"], sort_keys=True).encode()
    (E / "SPLITS.sha256").write_text(hashlib.sha256(test).hexdigest() + "  test split of eval/questions.json\n")
    print("written", len(qs))


if __name__ == "__main__":
    main()
