"""Recommendation engine scenario tests (Phase 16 requirements)."""
import pandas as pd

from app.recommend import build_recommendations

TH = {"shortage_ratio": -0.10, "balanced_max_ratio": 0.05,
      "low_surplus_max_ratio": 0.20, "min_transfer_units": 5,
      "max_distance_km": 5.0,
      "weights": {"need": 0.35, "quantity_fit": 0.25, "urgency": 0.20,
                  "proximity": 0.10, "compatibility": 0.10}}


def _frame(rows):
    cols = ["date", "location_id", "item_id", "category", "meal_period",
            "predicted_demand", "supply", "supply_basis", "surplus",
            "surplus_ratio", "status"]
    return pd.DataFrame(rows, columns=cols)


def _row(loc, demand, supply, status=None):
    surplus = None if supply is None else round(supply - demand, 2)
    if status is None:
        ratio = surplus / max(demand, 1)
        status = ("shortage" if ratio <= TH["shortage_ratio"] else
                  "balanced" if ratio <= TH["balanced_max_ratio"] else
                  "low_surplus" if ratio <= TH["low_surplus_max_ratio"]
                  else "high_surplus")
    return ["2026-08-22", loc, "I1", "hot_meal", "lunch",
            demand, supply, "estimated", surplus,
            surplus / max(demand, 1), status]


DISTS = pd.DataFrame({
    "from_location": ["SRC"] * 3,
    "to_location": ["DST-A", "DST-B", "DST-C"],
    "distance_km": [0.5, 2.0, 4.9],
})


def test_major_surplus_severe_shortage_produces_rec():
    f = _frame([_row("SRC", 100, 200), _row("DST-A", 100, 40)])
    recs = build_recommendations(f, DISTS, TH)
    assert len(recs) == 1
    r = recs[0]
    assert r["source_location"] == "SRC"
    assert r["destination_location"] == "DST-A"
    # transfer capped by destination need (60) and source surplus (100)
    assert abs(r["transfer_quantity"] - 60) < 1e-6
    assert 0 <= r["score"] <= 100
    assert r["factors"]["need"] > 0


def test_balanced_supply_no_rec():
    f = _frame([_row("SRC", 100, 102), _row("DST-A", 100, 99)])
    assert build_recommendations(f, DISTS, TH) == []


def test_small_surplus_below_min_units_skipped():
    f = _frame([_row("SRC", 100, 107), _row("DST-A", 100, 40)])
    # surplus 7 -> need 60; qty=7 >= min(5): allowed. Use surplus 4 instead.
    f2 = _frame([_row("SRC", 100, 104), _row("DST-A", 100, 40)])
    assert build_recommendations(f2, DISTS, TH) == []
    assert len(build_recommendations(f, DISTS, TH)) == 1


def test_no_eligible_destination():
    f = _frame([_row("SRC", 100, 200), _row("DST-A", 100, 150)])
    assert build_recommendations(f, DISTS, TH) == []


def test_multiple_destinations_ranked_by_need():
    f = _frame([_row("SRC", 100, 200),
                _row("DST-C", 100, 90),   # mild need
                _row("DST-A", 100, 30)])  # severe need
    recs = build_recommendations(f, DISTS, TH)
    assert len(recs) == 2
    top = recs[0]
    assert top["destination_location"] == "DST-A"   # bigger need wins
    assert recs[0]["score"] > recs[1]["score"]


def test_greedy_allocation_respects_source_limit():
    """Source has 60 units; two destinations want 50 each."""
    f = _frame([_row("SRC", 100, 160),
                _row("DST-A", 100, 50),
                _row("DST-B", 100, 50)])
    recs = build_recommendations(f, DISTS, TH)
    moved = sum(r["transfer_quantity"] for r in recs)
    assert moved <= 60 + 1e-6
    assert all(r["transfer_quantity"] > 0 for r in recs)


def test_same_location_never_recommends():
    f = _frame([_row("SRC", 100, 200), _row("SRC", 100, 40)])
    # second row overwrites key in real assess(); here both exist with same loc
    recs = build_recommendations(f, DISTS, TH)
    assert all(r["source_location"] != r["destination_location"] for r in recs)


def test_cross_item_never_recommends():
    f = _frame([_row("SRC", 100, 200)])
    g = _frame([_row("DST-A", 100, 40)])
    g["item_id"] = "I2"
    recs = build_recommendations(pd.concat([f, g], ignore_index=True),
                                 DISTS, TH)
    assert recs == []
