"""Data validation and cleaning pipeline.

Takes RAW service records (+ optional weather/context frames) and produces:
  * a CLEAN frame safe for feature engineering / modelling
  * a structured validation REPORT describing every issue found and every
    action taken. Nothing is silently altered.

Raw vs cleaned separation: raw CSVs are never modified; cleaned output is
written to a separate file by callers (see service.py).
"""
from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = [
    "date", "location_id", "item_id", "category", "meal_period",
    "planned_production", "actual_demand",
]
ALLOWED_MEAL_PERIODS = {"breakfast", "lunch", "dinner"}
SERIES_KEY = ["location_id", "item_id", "meal_period"]


def _empty_report() -> dict:
    return {
        "rows_in": 0,
        "rows_out": 0,
        "rows_dropped": 0,
        "issues": [],   # list of {check, severity, detail}
        "actions": [],  # list of {action, affected_rows, detail}
    }


def _issue(report: dict, check: str, severity: str, detail: str) -> None:
    report["issues"].append({"check": check, "severity": severity, "detail": detail})


def _action(report: dict, action: str, n: int, detail: str) -> None:
    if n > 0:
        report["actions"].append({"action": action, "affected_rows": int(n), "detail": detail})


def validate_schema(df: pd.DataFrame, report: dict) -> bool:
    """True if all required columns exist."""
    report["columns_present"] = sorted(df.columns.tolist())
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        _issue(report, "schema", "error", f"missing required columns: {missing}")
        return False
    return True


def validate_and_clean(
    services: pd.DataFrame,
    weather: pd.DataFrame | None = None,
    context_events: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Validate and clean raw service records. Returns (clean_df, report).

    Never mutates inputs.
    """
    report = _empty_report()
    report["rows_in"] = len(services)
    if not validate_schema(services, report):
        return pd.DataFrame(columns=REQUIRED_COLUMNS), report

    df = services.copy()

    # --- timestamps -------------------------------------------------------
    dates = pd.to_datetime(df["date"], errors="coerce")
    bad_dates = int(dates.isna().sum())
    if bad_dates:
        _issue(report, "timestamp", "error", f"{bad_dates} unparseable dates")
    df = df.assign(date=dates)
    df = df[df["date"].notna()]

    future = df["date"] > pd.Timestamp.today().normalize()
    if int(future.sum()):
        _issue(report, "timestamp", "warning",
               f"{int(future.sum())} rows dated in the future")
        df = df[~future]
    _action(report, "drop_invalid_dates", bad_dates, "unparseable or future dates removed")

    # --- identifiers & enums ---------------------------------------------
    for col in ("location_id", "item_id", "category"):
        blanks = int(df[col].isna().sum() + (df[col].astype(str).str.strip() == "").sum())
        if blanks:
            _issue(report, "identifiers", "error", f"{blanks} blank {col}")
            df = df[df[col].notna() & (df[col].astype(str).str.strip() != "")]
            _action(report, f"drop_blank_{col}", blanks, "blank identifier removed")

    bad_periods = ~df["meal_period"].isin(ALLOWED_MEAL_PERIODS)
    if int(bad_periods.sum()):
        _issue(report, "meal_period", "error",
               f"{int(bad_periods.sum())} unknown meal periods "
               f"({sorted(df.loc[bad_periods, 'meal_period'].unique())})")
        df = df[~bad_periods]
        _action(report, "drop_unknown_meal_periods", int(bad_periods.sum()),
                f"allowed: {sorted(ALLOWED_MEAL_PERIODS)}")

    # --- quantities -------------------------------------------------------
    for col in ("planned_production", "actual_demand"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    neg_mask = (df["actual_demand"] < 0) | (df["planned_production"] < 0)
    if int(neg_mask.sum()):
        _issue(report, "quantity", "error", f"{int(neg_mask.sum())} negative quantities")
        df = df[~neg_mask]
        _action(report, "drop_negative_quantities", int(neg_mask.sum()), "")

    missing_target = int(df["actual_demand"].isna().sum())
    if missing_target:
        _issue(report, "quantity", "error",
               f"{missing_target} rows without actual_demand (forecast target)")
        df = df[df["actual_demand"].notna()]
        _action(report, "drop_missing_actual_demand", missing_target, "")
    # planned_production may be missing: keep the row (forecast still valid),
    # surplus engine will report unknown supply instead of inventing one.
    missing_plan = int(df["planned_production"].isna().sum())
    if missing_plan:
        _issue(report, "quantity", "warning",
               f"{missing_plan} rows missing planned_production; "
               "kept, surplus reported as 'unknown_supply'")

    # --- duplicates -------------------------------------------------------
    dup_key = ["date"] + SERIES_KEY
    dups = df.duplicated(subset=dup_key, keep="first")
    if int(dups.sum()):
        examples = df[dups].head(3)[dup_key].to_dict("records")
        _issue(report, "duplicates", "warning",
               f"{int(dups.sum())} duplicate keys; first occurrence kept e.g. {examples}")
        df = df[~dups]
        _action(report, "deduplicate", int(dups.sum()), f"key={dup_key}")

    # --- outliers (per series, capped not deleted: spikes may be real) ----
    capped = 0
    if len(df):
        def _cap(s: pd.Series) -> pd.Series:
            nonlocal capped
            hi = s.quantile(0.995)
            over = s > hi
            capped += int(over.sum())
            return s.clip(upper=hi)
        df["actual_demand"] = df.groupby(SERIES_KEY)["actual_demand"].transform(_cap)
    _action(report, "winsorize_outliers", capped,
            "demand capped at per-series 99.5th percentile")

    # --- contextual joins --------------------------------------------------
    if weather is not None and len(weather):
        w = weather.copy()
        w["date"] = pd.to_datetime(w["date"], errors="coerce")
        w = w.dropna(subset=["date"]).drop_duplicates("date")
        df = df.merge(w[["date", "temp_c", "rain"]], on="date", how="left")
        miss_w = int(df["temp_c"].isna().sum())
        if miss_w:
            _issue(report, "context", "info",
                   f"{miss_w} rows lack weather; neutral defaults applied")
        df["temp_c"] = df["temp_c"].fillna(df["temp_c"].median() if df["temp_c"].notna().any() else 18.0)
        df["rain"] = df["rain"].fillna(0).astype(int)

    if context_events is not None and len(context_events):
        ce = context_events.copy()
        ce["date"] = pd.to_datetime(ce["date"], errors="coerce")
        ce = ce.dropna(subset=["date"])
        for evt in ("public_holiday", "mid_term_break", "exams", "term_start"):
            days_with_evt = set(ce.loc[ce["event_type"] == evt, "date"])
            df[evt] = df["date"].isin(days_with_evt).astype(int)
    else:
        for evt in ("public_holiday", "mid_term_break", "exams", "term_start"):
            df[evt] = 0

    # --- final shape -------------------------------------------------------
    df = df.sort_values(["date"] + SERIES_KEY).reset_index(drop=True)
    report["rows_out"] = len(df)
    report["rows_dropped"] = report["rows_in"] - len(df)
    return df, report


def health_check(clean: pd.DataFrame) -> dict:
    """Quick dataset health summary used by the dashboard/API."""
    if clean.empty:
        return {"healthy": False, "reason": "no usable rows after cleaning"}
    dates = pd.to_datetime(clean["date"])
    full_days = pd.date_range(dates.min(), dates.max(), freq="D")
    missing_days = sorted(set(full_days) - set(dates.unique()))
    zero_share = float((clean["actual_demand"] == 0).mean())
    healthy = (
        len(missing_days) <= 2
        and zero_share < 0.20
        and clean[SERIES_KEY].nunique().min() >= 1
    )
    return {
        "healthy": bool(healthy),
        "rows": int(len(clean)),
        "date_min": dates.min().date().isoformat(),
        "date_max": dates.max().date().isoformat(),
        "locations": int(clean["location_id"].nunique()),
        "items": int(clean["item_id"].nunique()),
        "zero_demand_share": round(zero_share, 4),
        "missing_service_days": [d.date().isoformat() for d in missing_days[:10]],
        "reason": "" if healthy else "gaps or zero-demand share above tolerance",
    }
