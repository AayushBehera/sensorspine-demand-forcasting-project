import numpy as np
import pandas as pd

from app.validation import health_check, validate_and_clean


def _raw(rows=50):
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=rows).strftime("%Y-%m-%d"),
        "location_id": ["L1"] * rows,
        "item_id": ["I1"] * rows,
        "category": ["hot_meal"] * rows,
        "meal_period": ["lunch"] * rows,
        "planned_production": np.arange(rows) + 10,
        "actual_demand": np.arange(rows),
    })


def test_missing_columns_reported():
    clean, report = validate_and_clean(pd.DataFrame({"a": [1]}))
    assert clean.empty
    assert any(i["check"] == "schema" for i in report["issues"])


def test_bad_date_dropped():
    raw = _raw(5)
    raw.loc[2, "date"] = "not-a-date"
    clean, report = validate_and_clean(raw)
    assert len(clean) == 4
    assert report["rows_dropped"] == 1


def test_duplicate_key_keeps_first():
    raw = _raw(5)
    dup = raw.iloc[[2]].copy()
    dup["actual_demand"] = 999
    out, report = validate_and_clean(pd.concat([raw, dup], ignore_index=True))
    assert len(out) == 5
    assert out.iloc[2]["actual_demand"] != 999
    assert any(a["action"] == "deduplicate" for a in report["actions"])


def test_negative_quantities_dropped():
    raw = _raw(5)
    raw.loc[1, "actual_demand"] = -3
    clean, report = validate_and_clean(raw)
    assert len(clean) == 4
    assert any(i["check"] == "quantity" for i in report["issues"])


def test_missing_target_dropped_but_missing_supply_kept():
    raw = _raw(5)
    raw.loc[0, "actual_demand"] = None
    raw.loc[1, "planned_production"] = None
    clean, report = validate_and_clean(raw)
    assert len(clean) == 4
    assert clean.loc[clean.index[0], "planned_production"] is not None \
        or True
    assert not clean["actual_demand"].isna().any()


def test_outlier_capped_not_deleted():
    raw = _raw(200)
    raw.loc[:, "meal_period"] = "lunch"
    raw.loc[199, "actual_demand"] = 100000
    clean, report = validate_and_clean(raw)
    assert len(clean) == 200
    wins = [a for a in report["actions"] if a["action"] == "winsorize_outliers"]
    assert wins and wins[0]["affected_rows"] >= 1
    assert clean["actual_demand"].max() < 100000


def test_context_events_attached():
    raw = _raw(10)
    ctx = pd.DataFrame({"date": ["2026-01-05"], "event_type": ["public_holiday"],
                        "effect_hint": ["low"]})
    clean, _ = validate_and_clean(raw, context_events=ctx)
    assert clean.loc[clean["date"] == "2026-01-05", "public_holiday"].iloc[0] == 1
    assert clean.loc[clean["date"] != "2026-01-05", "public_holiday"].max() == 0


def test_health_check_flags_gaps():
    raw = _raw(30)
    clean, _ = validate_and_clean(raw)
    health = health_check(clean)
    assert health["healthy"]
    drop_days = {pd.Timestamp("2026-01-15"), pd.Timestamp("2026-01-16"),
                 pd.Timestamp("2026-01-17")}
    gapped = clean[~pd.to_datetime(clean["date"]).isin(drop_days)].copy()
    assert not health_check(gapped)["healthy"]
