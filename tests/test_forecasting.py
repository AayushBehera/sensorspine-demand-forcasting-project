from app.forecasting import (confidence_for_prediction, forecast_future,
                             regression_metrics, train_and_evaluate)
from app.features import build_features, temporal_split


def test_metrics_math():
    m = regression_metrics(y_true=[10, 20], y_pred=[12, 18])
    assert abs(m["mae"] - 2.0) < 1e-9
    assert abs(m["rmse"] - 2.0) < 1e-9
    assert abs(m["bias"] - 0.0) < 1e-9
    assert abs(m["wape_pct"] - 100 * 4 / 30) < 1e-6


def test_candidate_beats_baselines(easy_data):
    feat = build_features(easy_data)
    tr, va, te = temporal_split(feat)
    res = train_and_evaluate(tr, va, te)
    m = res["metrics_test"]
    # The evidence-based selection picks a candidate that beats BOTH baselines.
    assert m[res["selected_strategy"]]["mae"] < m["seasonal_naive_lag7"]["mae"]
    assert m[res["selected_strategy"]]["mae"] < m["moving_avg_7"]["mae"]
    assert res["baselines_beaten"]
    assert res["selected_strategy"] in ("candidate_gbm", "ridge_linear")


def test_forecast_output_shape_and_confidence(small_clean):
    feat = build_features(small_clean)
    tr, va, te = temporal_split(feat)
    res = train_and_evaluate(tr, va, te)
    last = str(small_clean["date"].max().date())
    fc = forecast_future(small_clean, [last], res)
    n_series = small_clean[["location_id", "item_id", "meal_period"]].drop_duplicates().shape[0]
    assert len(fc) == n_series
    for col in ("predicted_demand", "interval_low", "interval_high",
                "stability_band", "model_version"):
        assert col in fc.columns
    assert (fc["interval_low"] <= fc["predicted_demand"]).all()
    assert (fc["interval_high"] >= fc["predicted_demand"]).all()
    assert set(fc["stability_band"]) <= {
        "stable", "moderate_uncertainty", "high_uncertainty"}


def test_confidence_band_logic():
    tight = confidence_for_prediction(100, -2, 2, 5, 100, True)
    wide = confidence_for_prediction(100, -60, 60, 60, 100, True)
    nodata = confidence_for_prediction(100, -2, 2, None, None, False)
    assert tight["stability_band"] == "stable"
    assert wide["stability_band"] != "stable"
    assert nodata["stability_band"] == "high_uncertainty"
    assert tight["interval_low"] < 100 < tight["interval_high"]


def test_zero_demand_edge(easy_data):
    feat = build_features(easy_data)
    feat["actual_demand"] = 0
    tr, va, te = temporal_split(feat)
    res = train_and_evaluate(tr, va, te)
    # must not crash and WAPE guard handles zero denominator
    assert "candidate_gbm" in res["metrics_test"]
