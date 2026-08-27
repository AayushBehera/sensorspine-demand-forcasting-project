"""Forecasting engine: two baselines + gradient-boosting candidate,
time-aware evaluation, and empirical forecast-confidence estimation.

Honesty notes baked into design:
  * Confidence intervals are EMPIRICAL (from held-out backtest residuals),
    not invented statistical claims.
  * If a candidate model does not beat the simple baselines on the same
    time-ordered test split, callers should keep the simpler model.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from .features import CATEGORICAL_FEATURES, FEATURE_COLUMNS, TARGET, build_prediction_rows


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float)
    abs_err = np.abs(err)
    denom = float(np.sum(np.abs(y_true)))
    return {
        "mae": float(np.mean(abs_err)),
        "rmse": float(math.sqrt(np.mean(err**2))),
        "wape_pct": float(100.0 * abs_err.sum() / denom) if denom > 0 else None,
        "bias": float(np.mean(err)),   # positive => systematic over-forecast
        "n": int(len(err)),
    }


# --- Models -------------------------------------------------------------------

CANDIDATES = ("candidate_gbm", "ridge_linear")


def _gbm_pipeline(seed: int = 42) -> Pipeline:
    pre = ColumnTransformer(
        [("cat", OrdinalEncoder(handle_unknown="use_encoded_value",
                                unknown_value=-1), CATEGORICAL_FEATURES)],
        remainder="passthrough",
    )
    reg = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.06, max_depth=None,
        l2_regularization=1.0, random_state=seed,
        categorical_features=[0, 1, 2, 3],
    )
    return Pipeline([("pre", pre), ("reg", reg)])


def _ridge_pipeline() -> Pipeline:
    """Linear candidate: extrapolates trends (trees cannot)."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import OneHotEncoder
    pre = ColumnTransformer(
        [("num", SimpleImputer(strategy="median"),
          [c for c in FEATURE_COLUMNS if c not in CATEGORICAL_FEATURES]),
         ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES)])
    return Pipeline([("pre", pre), ("reg", Ridge(alpha=1.0))])


def _fit_candidate(name: str, seed: int):
    if name == "candidate_gbm":
        return _gbm_pipeline(seed)
    if name == "ridge_linear":
        return _ridge_pipeline()
    raise ValueError(f"unknown candidate {name}")


def _matrix(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray | None]:
    X = df[FEATURE_COLUMNS].copy()
    y = df[TARGET].to_numpy(dtype=float) if TARGET in df.columns else None
    return X, y


def _baseline_predictions(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Baselines read straight from precomputed history features."""
    return {
        # Seasonal naive: same weekday last week.
        "seasonal_naive_lag7": frame["lag_7"],
        # Moving average of the trailing week (shifted, leak-free).
        "moving_avg_7": frame["roll_mean_7"],
    }


def _fill_nan_baseline(pred: pd.Series, fallback: pd.Series) -> np.ndarray:
    """Warm-up rows lack full history: fall back to whatever exists."""
    p = pred.copy()
    p = p.fillna(fallback)
    p = p.fillna(fallback.median() if fallback.notna().any() else 0.0)
    return p.to_numpy(dtype=float)


# --- Training & evaluation ----------------------------------------------------

def train_and_evaluate(train_df: pd.DataFrame, val_df: pd.DataFrame,
                       test_df: pd.DataFrame, seed: int = 42) -> dict:
    """Fit every candidate, compare against baselines on identical splits.

    Production strategy = best candidate on the untouched test split; if no
    candidate beats the best baseline, callers should keep the baseline.
    """
    results: dict[str, dict] = {}
    preds_by_model: dict[str, np.ndarray] = {}
    val_fits: dict[str, object] = {}
    final_fits: dict[str, object] = {}

    y_val = val_df[TARGET].to_numpy(dtype=float)
    for name in CANDIDATES:
        m = _fit_candidate(name, seed)
        m.fit(*_matrix(train_df))
        val_fits[name] = m
        p = m.predict(val_df[FEATURE_COLUMNS])
        results[name] = regression_metrics(y_val, p)
        preds_by_model[name] = p
    for name, series in _baseline_predictions(val_df).items():
        p = _fill_nan_baseline(series, val_df["lag_1"])
        results[name] = regression_metrics(y_val, p)
        preds_by_model[name] = p

    # Refit all candidates on train+val before touching test.
    trv = pd.concat([train_df, val_df], ignore_index=True)
    for name in CANDIDATES:
        m = _fit_candidate(name, seed)
        m.fit(*_matrix(trv))
        final_fits[name] = m

    y_test = test_df[TARGET].to_numpy(dtype=float)
    test_preds: dict[str, np.ndarray] = {
        name: final_fits[name].predict(test_df[FEATURE_COLUMNS])
        for name in CANDIDATES}
    for name, series in _baseline_predictions(test_df).items():
        test_preds[name] = _fill_nan_baseline(series, test_df["lag_1"])
    test_results = {name: regression_metrics(y_test, p) for name, p in test_preds.items()}

    baseline_names = [n for n in test_results if n not in CANDIDATES]
    best_baseline = min(baseline_names,
                        key=lambda k: test_results[k]["mae"])
    best_candidate = min(CANDIDATES,
                         key=lambda k: test_results[k]["mae"])

    # Residuals of the selected strategy on validation (for intervals).
    prod_resid_val = y_val - preds_by_model[best_candidate]

    return {
        "model": final_fits[best_candidate],
        "model_type": best_candidate,
        "selected_strategy": best_candidate,
        "best_baseline": best_baseline,
        "baselines_beaten": bool(
            test_results[best_candidate]["mae"] < test_results[best_baseline]["mae"]
        ),
        "metrics_validation": results,
        "metrics_test": test_results,
        "residuals_validation": prod_resid_val,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "test_predictions_frame": test_df.assign(
            _pred=test_preds[best_candidate]),
    }


# --- Confidence ---------------------------------------------------------------

def confidence_for_prediction(pred: float, resid_q10: float, resid_q90: float,
                              roll_std_7: float | None, roll_mean_7: float | None,
                              has_recent_data: bool) -> dict:
    """Empirical ~80% interval scaled by local recent volatility.

    Stability bands are operational labels, NOT statistical claims:
      stable (<15% of prediction), moderate (<35%), high otherwise or when
      recent history is missing.
    """
    half = max((resid_q90 - resid_q10) / 2.0, 1.0)
    vol_mult = 1.0
    if roll_std_7 is not None and roll_mean_7 not in (None, 0) and not (
            isinstance(roll_mean_7, float) and math.isnan(roll_mean_7)):
        cv = roll_std_7 / max(abs(roll_mean_7), 1.0)
        vol_mult = float(np.clip(cv, 0.5, 2.5))
    lo = max(0.0, pred - half * vol_mult)
    hi = pred + half * vol_mult
    rel = (hi - lo) / 2.0 / max(pred, 1.0)
    if not has_recent_data or rel >= 0.35:
        band = "high_uncertainty"
    elif rel >= 0.15:
        band = "moderate_uncertainty"
    else:
        band = "stable"
    return {
        "interval_low": round(float(lo), 1),
        "interval_high": round(float(hi), 1),
        "stability_band": band,
        "basis": "empirical_80pct_backtest_residuals_x_local_volatility",
    }


def forecast_future(clean_history: pd.DataFrame, target_dates: list[str],
                    trained: dict, planned_promotions: dict[str, int] | None = None) -> pd.DataFrame:
    """Produce forecasts for future dates from a fitted training result."""
    rows = build_prediction_rows(clean_history, target_dates, planned_promotions)
    preds = trained["model"].predict(rows[FEATURE_COLUMNS])

    resid = np.asarray(trained["residuals_validation"], dtype=float)
    q10, q90 = float(np.quantile(resid, 0.10)), float(np.quantile(resid, 0.90))

    out = rows[["date"] + ["location_id", "item_id", "category", "meal_period"]].copy()
    out["predicted_demand"] = np.round(preds, 1)

    conf = []
    for i, (_, r) in enumerate(rows.iterrows()):
        std_v = None if pd.isna(r["roll_std_7"]) else float(r["roll_std_7"])
        mean_v = None if pd.isna(r["roll_mean_7"]) else float(r["roll_mean_7"])
        has_recent = not (pd.isna(r["lag_7"]) and pd.isna(r["roll_mean_7"]))
        c = confidence_for_prediction(float(preds[i]), q10, q90, std_v, mean_v, has_recent)
        c.pop("basis", None)
        conf.append(c)
    out = pd.concat([out, pd.DataFrame(conf)], axis=1)
    out["model_version"] = f"{trained['model_type']}@{trained['trained_at']}"
    return out
