import pandas as pd

from app.features import (FEATURE_COLUMNS, build_features,
                          build_prediction_rows, temporal_split)


def test_supervised_frame_shape_and_columns(small_clean):
    feat = build_features(small_clean)
    assert not feat.empty
    for col in ["date", "location_id", "item_id", "meal_period",
                *FEATURE_COLUMNS, "actual_demand"]:
        assert col in feat.columns, col


def test_lag_alignment_on_calendar_gaps(small_clean):
    """lag_7 must equal demand exactly 7 calendar days earlier, even if a
    series skipped days."""
    feat = build_features(small_clean)
    key = feat[["location_id", "item_id", "meal_period"]].iloc[0].tolist()
    g = feat[(feat.location_id == key[0]) & (feat.item_id == key[1])
             & (feat.meal_period == key[2])].set_index("date")
    demand = small_clean[
        (small_clean.location_id == key[0])
        & (small_clean.item_id == key[1])
        & (small_clean.meal_period == key[2])].set_index("date")["actual_demand"]
    checked = 0
    for d, row in g.iterrows():
        prev7 = d - pd.Timedelta(days=7)
        if prev7 in demand.index and pd.notna(row["lag_7"]):
            assert row["lag_7"] == demand.loc[prev7]
            checked += 1
    assert checked > 10


def test_no_leakage_perturb_future(small_clean):
    """Tripling all demand AFTER a cutoff must not change any feature value
    before the cutoff."""
    cutoff = small_clean["date"].quantile(0.6, interpolation="lower")
    before = build_features(small_clean)
    before = before[before["date"] <= cutoff].drop(
        columns=["planned_production"]).reset_index(drop=True)

    pert = small_clean.copy()
    pert.loc[pert["date"] > cutoff, "actual_demand"] *= 3
    after = build_features(pert)
    after = after[after["date"] <= cutoff].drop(
        columns=["planned_production"]).reset_index(drop=True)

    pd.testing.assert_frame_equal(before, after)


def test_temporal_split_is_time_ordered(small_clean):
    feat = build_features(small_clean)
    tr, va, te = temporal_split(feat)
    assert tr["date"].max() < va["date"].min()
    assert va["date"].max() < te["date"].min()


def test_prediction_rows_use_only_past(small_clean):
    target = str((small_clean["date"].max() + pd.Timedelta(days=3)).date())
    hist = small_clean[small_clean["date"]
                       < small_clean["date"].max() + pd.Timedelta(days=1)]
    rows = build_prediction_rows(hist, [target])
    n_series = hist[["location_id", "item_id", "meal_period"]].drop_duplicates().shape[0]
    assert len(rows) == n_series
