import pandas as pd

from app.surplus import assess, classify_status, estimate_supply, summarize_day

TH = {"shortage_ratio": -0.10, "balanced_max_ratio": 0.05,
      "low_surplus_max_ratio": 0.20}


def test_status_bands():
    assert classify_status(-20, 100, TH) == "shortage"       # -20%
    assert classify_status(3, 100, TH) == "balanced"          # +3%
    assert classify_status(15, 100, TH) == "low_surplus"      # +15%
    assert classify_status(50, 100, TH) == "high_surplus"     # +50%
    # boundary behaviour
    assert classify_status(-10, 100, TH) == "shortage"
    assert classify_status(5, 100, TH) == "balanced"
    assert classify_status(20, 100, TH) == "low_surplus"


def _forecast_frame(demand):
    n = len(demand)
    return pd.DataFrame({
        "date": ["2026-08-22"] * n,
        "location_id": [f"L{i}" for i in range(n)],
        "item_id": ["I1"] * n,
        "category": ["hot_meal"] * n,
        "meal_period": ["lunch"] * n,
        "predicted_demand": demand,
        "interval_low": demand, "interval_high": demand,
        "stability_band": ["stable"] * n,
        "model_version": ["test"] * n,
    })


def test_assess_and_summarize():
    fc = _forecast_frame([100.0, 100.0, 100.0, 100.0])
    supply = pd.DataFrame({
        "location_id": [f"L{i}" for i in range(4)],
        "item_id": ["I1"] * 4, "category": ["hot_meal"] * 4,
        "meal_period": ["lunch"] * 4,
        "supply": [60.0, 102.0, 110.0, None],
        "supply_basis": ["estimated"] * 4,
    })
    a = assess(fc, supply, TH)
    statuses = a.set_index("location_id")["status"]
    assert statuses["L0"] == "shortage"
    assert statuses["L1"] == "balanced"
    assert statuses["L2"] == "low_surplus"
    assert statuses["L3"] == "unknown_supply"

    s = summarize_day(a)
    assert s["series_total"] == 4
    assert s["unknown_supply_series"] == 1
    # L1 balanced (+2) and L2 low (+10) both count toward expected leftover
    assert abs(s["total_expected_surplus"] - 12.0) < 1e-9
    assert abs(s["at_risk_units"] - 40.0) < 1e-9


def test_supply_estimation_from_history(small_clean):
    est = estimate_supply(small_clean)
    assert not est.empty
    assert (est["supply"] >= 0).all()
    assert (est["supply_basis"] == "estimated").all()
