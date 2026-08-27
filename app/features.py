"""Leak-safe feature engineering.

LEAKAGE RULES enforced here:
  1. Every history-derived feature uses only data STRICTLY BEFORE the row's
     date (lags are shifted; rolling windows end at t-1).
  2. `planned_production` is deliberately NOT a model feature: the forecast
     must stay independent of the production plan, otherwise the surplus
     engine ("plan - forecast") would be circular and useless.
  3. Same-day weather is unknown when forecasting the next day. Historical
     training rows use previous-day weather (temp_prev/rain_prev); prediction
     rows leave it missing and the model handles NaN natively.
  4. Promotions are treated as PLANNED events known in advance (campus
     practice). Future promo flags come from caller input; default 0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SERIES_KEY = ["location_id", "item_id", "meal_period"]

CATEGORICAL_FEATURES = ["location_id", "item_id", "category", "meal_period"]

NUMERIC_FEATURES = [
    "dow", "month", "is_weekend",
    "dow_sin", "dow_cos", "month_sin", "month_cos",
    "public_holiday", "mid_term_break", "exams", "term_start",
    "promotion",
    "temp_c", "rain",
    "lag_1", "lag_7", "lag_14",
    "roll_mean_7", "roll_mean_28", "roll_std_7", "trend_7_28",
]

FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "actual_demand"


def _calendar_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    dow = dates.dayofweek.to_numpy()
    month = dates.month.to_numpy()
    return pd.DataFrame({
        "date": dates,
        "dow": dow,
        "month": month,
        "is_weekend": (dow >= 5).astype(int),
        "dow_sin": np.sin(2 * np.pi * dow / 7.0),
        "dow_cos": np.cos(2 * np.pi * dow / 7.0),
        "month_sin": np.sin(2 * np.pi * (month - 1) / 12.0),
        "month_cos": np.cos(2 * np.pi * (month - 1) / 12.0),
    })


def _add_history_features(g: pd.DataFrame) -> pd.DataFrame:
    """Vectorised features for one series. g sorted by date, indexed by date."""
    d = g["actual_demand"].shift(1)          # yesterday's demand
    g = g.copy()
    g["lag_1"] = d.shift(0)
    g["lag_7"] = d.shift(6)
    g["lag_14"] = d.shift(13)
    g["roll_mean_7"] = d.rolling(7, min_periods=3).mean()
    g["roll_mean_28"] = d.rolling(28, min_periods=7).mean()
    g["roll_std_7"] = d.rolling(7, min_periods=3).std()
    g["trend_7_28"] = g["roll_mean_7"] / g["roll_mean_28"]
    return g


def build_features(clean: pd.DataFrame) -> pd.DataFrame:
    """Build the full supervised frame (features + target) from clean records.

    One row per operating (date, location, item, meal_period) record present
    in `clean`. Calendar gaps inside a series do not corrupt lag alignment:
    each series is reindexed to a complete daily grid before shifting.
    """
    frames = []
    for key, grp in clean.groupby(SERIES_KEY, sort=False):
        g = grp.sort_values("date").set_index("date")
        operated_on = g.index.copy()                      # real service days
        full_idx = pd.date_range(g.index.min(), g.index.max(), freq="D")
        g = g.reindex(full_idx)

        cal = _calendar_frame(full_idx).set_index("date")
        g["dow"] = cal["dow"]
        g["month"] = cal["month"]
        g["is_weekend"] = cal["is_weekend"]
        g["dow_sin"] = cal["dow_sin"]; g["dow_cos"] = cal["dow_cos"]
        g["month_sin"] = cal["month_sin"]; g["month_cos"] = cal["month_cos"]
        # Previous-day weather (same-day weather is future information).
        g["temp_c"] = g["temp_c"].shift(1)
        g["rain"] = g["rain"].shift(1)
        for evt in ("public_holiday", "mid_term_break", "exams", "term_start"):
            if evt not in g.columns:
                g[evt] = 0
            else:
                g[evt] = g[evt].fillna(0).astype(int)
        if "promotion" not in g.columns:
            g["promotion"] = 0
        else:
            g["promotion"] = g["promotion"].fillna(0).astype(int)

        g = _add_history_features(g)

        g = g.loc[g.index.isin(operated_on)]              # drop calendar gaps
        g = g.reset_index().rename(columns={"index": "date"})
        for kcol, kval in zip(SERIES_KEY, key):
            g[kcol] = kval
        frames.append(g)

    out = pd.concat(frames, ignore_index=True)
    keep: list[str] = []
    for c in (["date"] + SERIES_KEY + FEATURE_COLUMNS + [TARGET, "planned_production"]):
        if c in out.columns and c not in keep:
            keep.append(c)
    return out[keep].sort_values(["date"] + SERIES_KEY).reset_index(drop=True)


def build_prediction_rows(
    history_clean: pd.DataFrame,
    target_dates: list[str],
    planned_promotions: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Feature rows for FUTURE dates given history ending before them.

    Returns one row per (target_date x active series), with keys + features.
    `history_clean` must contain no rows on/after any target date.
    """
    planned_promotions = planned_promotions or {}
    targets = pd.to_datetime(pd.Index(target_dates))

    frames = []
    for key, grp in history_clean.groupby(SERIES_KEY, sort=False):
        loc_id, item_id, period = key
        category = grp["category"].iloc[-1]
        g = grp.sort_values("date").set_index("date")
        # Reindex through the LAST target date so shifts land correctly.
        full_idx = pd.date_range(g.index.min(), targets.max(), freq="D")
        g = g.reindex(full_idx)

        cal = _calendar_frame(full_idx).set_index("date")
        g["dow"] = cal["dow"]; g["month"] = cal["month"]; g["is_weekend"] = cal["is_weekend"]
        g["dow_sin"] = cal["dow_sin"]; g["dow_cos"] = cal["dow_cos"]
        g["month_sin"] = cal["month_sin"]; g["month_cos"] = cal["month_cos"]
        # Previous-day weather (same-day weather is future information).
        g["temp_c"] = g["temp_c"].shift(1)
        g["rain"] = g["rain"].shift(1)
        for evt in ("public_holiday", "mid_term_break", "exams", "term_start"):
            g[evt] = g[evt].fillna(0).astype(int) if evt in g.columns else 0
        g["promotion"] = 0
        g = _add_history_features(g)
        g = g.loc[targets.intersection(g.index)]          # only target dates

        g = g.reset_index().rename(columns={"index": "date"})
        g["location_id"], g["item_id"], g["meal_period"] = loc_id, item_id, period
        g["category"] = category
        # Planned promotions keyed "YYYY-MM-DD|ITEM_ID".
        mask = g["date"].dt.strftime("%Y-%m-%d") + "|" + item_id
        g["promotion"] = mask.map(planned_promotions).fillna(0).astype(int)
        frames.append(g)

    out = pd.concat(frames, ignore_index=True)
    cols: list[str] = []
    for c in (["date"] + SERIES_KEY + FEATURE_COLUMNS):
        if c in out.columns and c not in cols:
            cols.append(c)
    return out[cols].sort_values(["date"] + SERIES_KEY).reset_index(drop=True)


def temporal_split(df: pd.DataFrame, train_frac: float = 0.70,
                   val_frac: float = 0.15) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Time-ordered split by unique dates. No shuffling anywhere."""
    days = np.array(sorted(df["date"].unique()))
    n = len(days)
    t_end = days[int(n * train_frac)]
    v_end = days[int(n * (train_frac + val_frac))]
    train = df[df["date"] <= t_end]
    val = df[(df["date"] > t_end) & (df["date"] <= v_end)]
    test = df[df["date"] > v_end]
    return train, val, test
