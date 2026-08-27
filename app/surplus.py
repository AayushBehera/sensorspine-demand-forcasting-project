"""Surplus / shortage engine.

Expected surplus = planned (or estimated) supply - forecast demand.
Status bands are configurable in config/thresholds.json.

Supply honesty: every assessment carries `supply_basis`:
  * "confirmed"   - operator posted an actual production plan
  * "estimated"   - system inferred it from recent planning behaviour
A forecast is never treated as ground truth; outputs are always labelled
predicted/expected, never actual.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import get_thresholds

KEY_COLS = ["location_id", "item_id", "category", "meal_period"]


def estimate_supply(history_clean: pd.DataFrame, lookback_days: int = 14) -> pd.DataFrame:
    """Fallback supply estimate per series: median recent planned production."""
    h = history_clean.copy()
    h["date"] = pd.to_datetime(h["date"])
    cutoff = h["date"].max() - pd.Timedelta(days=lookback_days)
    recent = h[h["date"] > cutoff]
    est = (recent.groupby(KEY_COLS)["planned_production"]
                 .median().rename("supply").reset_index())
    est["supply_basis"] = "estimated"
    return est


def confirmed_supply(plans: list[dict]) -> pd.DataFrame:
    """Operator-provided plans: [{date?, location_id, item_id, meal_period, supply}]."""
    df = pd.DataFrame(plans)
    required = {"location_id", "item_id", "meal_period", "supply"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"confirmed plans missing fields: {sorted(missing)}")
    return df.rename(columns={"supply": "supply"}).assign(supply_basis="confirmed")


def classify_status(expected_surplus: float, predicted_demand: float,
                    thresholds: dict | None = None) -> str:
    th = thresholds or get_thresholds()
    denom = max(predicted_demand, 1.0)
    ratio = expected_surplus / denom
    if ratio <= th["shortage_ratio"]:
        return "shortage"
    if ratio <= th["balanced_max_ratio"]:
        return "balanced"
    if ratio <= th["low_surplus_max_ratio"]:
        return "low_surplus"
    return "high_surplus"


STATUS_LABELS = {
    "shortage": "Shortage risk",
    "balanced": "Balanced",
    "low_surplus": "Low surplus",
    "high_surplus": "High surplus",
}


def assess(forecasts: pd.DataFrame,
           supply: pd.DataFrame,
           thresholds: dict | None = None) -> pd.DataFrame:
    """Join forecasts (per key/date) with supply and classify each series."""
    th = thresholds or get_thresholds()
    f = forecasts.copy()
    s = supply[[c for c in ["date"] + KEY_COLS + ["supply", "supply_basis"]]
               if "date" in supply.columns
               else KEY_COLS + ["supply", "supply_basis"]]
    join_on = [c for c in ["date"] + KEY_COLS if c in f.columns and c in s.columns]
    out = f.merge(s, on=join_on, how="left")

    def _ratio(row):
        return row["surplus"] / max(row["predicted_demand"], 1.0)

    out["surplus"] = out["supply"] - out["predicted_demand"]
    out["status"] = [
        classify_status(row["surplus"], row["predicted_demand"], th)
        if pd.notna(row["supply"]) else "unknown_supply"
        for _, row in out.iterrows()
    ]
    out["surplus_ratio"] = out.apply(_ratio, axis=1)
    cols = ([c for c in ("date",) if c in out.columns]
            + KEY_COLS
            + ["predicted_demand", "supply", "supply_basis", "surplus",
               "surplus_ratio", "status"]
            + [c for c in ("interval_low", "interval_high", "stability_band",
                           "model_version") if c in out.columns])
    return out[cols]


def summarize_day(assessment: pd.DataFrame) -> dict:
    """Operational headline numbers for one date."""
    known = assessment[assessment["status"] != "unknown_supply"]
    surplus_rows = known[known["surplus"] > 0]
    shortage_rows = known[known["status"] == "shortage"]
    return {
        "series_total": int(len(assessment)),
        "unknown_supply_series": int((assessment["status"] == "unknown_supply").sum()),
        "total_predicted_demand": float(np.nansum(known["predicted_demand"])),
        "total_supply": float(np.nansum(known["supply"])),
        "total_expected_surplus": float(np.nansum(surplus_rows["surplus"])),
        "high_surplus_series": int((known["status"] == "high_surplus").sum()),
        "shortage_series": int(len(shortage_rows)),
        "at_risk_units": float(np.nansum(
            shortage_rows["predicted_demand"] - shortage_rows["supply"])),
        "confidence_mix": {
            band: int(n) for band, n in
            (known["stability_band"].value_counts().items()
             if "stability_band" in known.columns and len(known) else [])
        },
    }
