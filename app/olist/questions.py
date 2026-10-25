"""The 3 Olist business questions. Each hypothesis is tested by one or two SQL comparisons
(treatment vs control). The decision rule is the same for every comparison and fixed in code:

  ratio = treatment / control
  supports    if ratio >= SUPPORT_RATIO (1.25)
  refutes     if ratio <= REFUTE_RATIO  (1.10)
  inconclusive otherwise
A hypothesis with several comparisons is supported only if all support, refuted if any refutes.
`prior` is the fixed order in which the planner opens hypotheses (written before running, not learned).
"""
from __future__ import annotations

SUPPORT_RATIO, REFUTE_RATIO = 1.25, 1.10

JAN18, FEBMAR18 = ["2018-01-01", "2018-01-31"], ["2018-02-01", "2018-03-31"]
OCT17, NOV17 = ["2017-10-01", "2017-10-31"], ["2017-11-01", "2017-11-30"]
ALL = ["2017-01-01", "2018-08-31"]


def cmp(eid, metric, treat, ctrl, label):
    return {"id": eid, "metric": metric, "treatment": treat, "control": ctrl, "label": label}


QUESTIONS = {
    "olist_q1": {
        "title": "Why did the late-delivery rate jump in Feb-Mar 2018 compared with Jan 2018?",
        "kpi": ("olist.late_rate", {"window": FEBMAR18}, {"window": JAN18}),
        "hypotheses": [
            {"id": "H_transit", "text": "Carrier transit time (handed to carrier -> delivered) got longer",
             "tests": [cmp("q1_transit", "olist.avg_transit_days", {"window": FEBMAR18}, {"window": JAN18}, "avg transit days")]},
            {"id": "H_volume", "text": "Order volume rose and overloaded the network",
             "tests": [cmp("q1_volume", "olist.orders_per_day", {"window": FEBMAR18}, {"window": JAN18}, "delivered orders per day")]},
            {"id": "H_handling", "text": "Sellers took longer to hand orders to the carrier",
             "tests": [cmp("q1_handling", "olist.avg_handling_days", {"window": FEBMAR18}, {"window": JAN18}, "avg seller handling days")]},
            {"id": "H_rj_only", "text": "The rise is confined to Rio de Janeiro (RJ) customers; the rest of Brazil did not get worse",
             "tests": [cmp("q1_rest", "olist.late_rate", {"window": FEBMAR18, "not_state": "RJ"}, {"window": JAN18, "not_state": "RJ"},
                           "late rate outside RJ (if it also rose, the rise is NOT RJ-only)")], "invert": True},
        ],
    },
    "olist_q2": {
        "title": "Why did the late-delivery rate spike in November 2017 (Black Friday month) compared with October 2017?",
        "kpi": ("olist.late_rate", {"window": NOV17}, {"window": OCT17}),
        "hypotheses": [
            {"id": "H_volume", "text": "Black Friday order volume surge",
             "tests": [cmp("q2_volume", "olist.orders_per_day", {"window": NOV17}, {"window": OCT17}, "delivered orders per day")]},
            {"id": "H_handling", "text": "Sellers took longer to hand orders to the carrier",
             "tests": [cmp("q2_handling", "olist.avg_handling_days", {"window": NOV17}, {"window": OCT17}, "avg seller handling days")]},
            {"id": "H_transit", "text": "Carrier transit time got longer",
             "tests": [cmp("q2_transit", "olist.avg_transit_days", {"window": NOV17}, {"window": OCT17}, "avg transit days")]},
        ],
    },
    "olist_q3": {
        "title": "What drives 1-2 star reviews (orders purchased Jan 2017 - Aug 2018)?",
        "kpi": ("olist.low_review_rate", {"window": ALL}, None),
        "hypotheses": [
            {"id": "H_freight", "text": "Orders where freight is >= 30% of the item price get worse reviews",
             "tests": [cmp("q3_freight", "olist.low_review_rate", {"window": ALL, "group": "freight_heavy"},
                           {"window": ALL, "group": "freight_heavy", "in_group": False}, "1-2 star share, freight-heavy vs not")]},
            {"id": "H_late", "text": "Late deliveries get worse reviews",
             "tests": [cmp("q3_late", "olist.low_review_rate", {"window": ALL, "group": "late"},
                           {"window": ALL, "group": "late", "in_group": False}, "1-2 star share, late vs on time")]},
            {"id": "H_interstate", "text": "Orders shipped from a seller in another state get worse reviews",
             "tests": [cmp("q3_interstate", "olist.low_review_rate", {"window": ALL, "group": "interstate"},
                           {"window": ALL, "group": "interstate", "in_group": False}, "1-2 star share, interstate vs same state")]},
            {"id": "H_multi_seller", "text": "Orders split across several sellers get worse reviews",
             "tests": [cmp("q3_multi", "olist.low_review_rate", {"window": ALL, "group": "multi_seller"},
                           {"window": ALL, "group": "multi_seller", "in_group": False}, "1-2 star share, multi-seller vs single")]},
        ],
    },
}
