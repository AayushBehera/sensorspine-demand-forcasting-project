"""India-context bridge: connects the validated data layers under
data/processed/ to the operational simulator and ML pipeline.

What is REAL here (never fabricated):
  * daily Bengaluru weather  - Open-Meteo ERA5 archive
  * Indian public holidays   - `holidays` package (official gazette calendars)
  * HCES category shares     - official MoSPI microdata (consumption prior)

What stays SYNTHETIC (clearly labelled by callers):
  * campus transactions, academic calendar, distances, supply behaviour
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .config import DATA_DIR

PROCESSED = DATA_DIR / "processed"


@lru_cache(maxsize=1)
def load_weather_table() -> pd.DataFrame:
    """REAL Bengaluru ERA5 daily weather as {date: (temp_c, precip_mm)}."""
    p = PROCESSED / "weather" / "bengaluru_era5_daily.csv"
    if not p.exists():
        return pd.DataFrame(columns=["date", "temp_c", "rain"])
    df = pd.read_csv(p)
    if "precip_mm" not in df.columns:
        return pd.DataFrame(columns=["date", "temp_c", "rain"])
    df["date"] = pd.to_datetime(df["date"])
    df["rain"] = (df["precip_mm"].fillna(0) > 0).astype(int)
    return df[["date", "temp_c", "rain"]]


@lru_cache(maxsize=1)
def load_india_holidays() -> set[str]:
    """REAL Indian public-holiday dates (ISO strings)."""
    p = PROCESSED / "context" / "india_public_holidays.csv"
    if not p.exists():
        return set()
    return {ln.split(",")[0]
            for ln in p.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()}


@lru_cache(maxsize=1)
def hces_category_value_shares() -> dict[str, float]:
    """Official HCES 2023-24 Bengaluru value-share by food category."""
    p = PROCESSED / "consumption" / "hces_bengaluru_category_shares.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    return {r.food_category: float(r.value_share_pct) for r in df.itertuples()
            if r.food_category != "other"}


# --- user-collected official/community layers -----------------------------------

def latest_food_inflation() -> dict | None:
    """Latest published y-o-y food-price inflation from RS-251 table."""
    p = PROCESSED / "context" / "india_food_inflation_monthly.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p).dropna(subset=["inflation_pct"])
    if df.empty:
        return None
    row = df.sort_values(["year", "month"]).iloc[-1]
    return {"year": int(row["year"]), "month": str(row["month"]),
            "inflation_pct": round(float(row["inflation_pct"]), 2),
            "provisional": bool(row.get("provisional", False))}


def india_waste_facts() -> dict | None:
    """UNEP FWI sector split for India (food service is our domain)."""
    p = PROCESSED / "waste" / "unep_fwi_by_country_sectors.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    row = df[df["is_india"]]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "combined_kg_pc_yr": float(r["combined_kg_pc_yr"]),
        "household_kg_pc_yr": float(r["household_kg_pc_yr"]),
        "retail_kg_pc_yr": float(r["retail_kg_pc_yr"]),
        "food_service_kg_pc_yr": float(r["food_service_kg_pc_yr"]),
        "confidence": str(r["confidence"]),
    }


def demand_behaviour_facts() -> dict | None:
    """Online-food survey (Bengaluru): share ordering online."""
    p = PROCESSED / "restaurant" / "online_food_orders_bangalore.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if df.empty:
        return None
    return {"respondents": int(len(df)),
            "order_rate_pct": round(100 * float(df["ordered_online"].mean()), 1),
            "city": str(df["city"].iloc[0])}


def supply_facts() -> dict:
    """Official national supply references (crops, stocks, capacity)."""
    out = {}
    p = PROCESSED / "supply" / "crop_production_national.csv"
    if p.exists():
        df = pd.read_csv(p).dropna(subset=["production_mt"])
        top = df.nlargest(3, "production_mt")[["crop", "production_mt"]]
        out["top_crops_mt"] = [{"crop": r.crop,
                                "million_tonnes": round(float(r.production_mt), 1)}
                               for r in top.itertuples()]
    p = PROCESSED / "institutional" / "avg_foodgrain_stocks_yearly.csv"
    if p.exists():
        df = pd.read_csv(p).dropna(subset=["avg_stock_mt_central_pool"])
        if len(df):
            last = df.iloc[-1]
            out["latest_buffer_stock"] = {
                "year": str(last["year"]),
                "avg_stock_mt": float(last["avg_stock_mt_central_pool"])}
    p = PROCESSED / "institutional" / "food_processing_capacity_by_state.csv"
    if p.exists():
        df = pd.read_csv(p).dropna(subset=["factories_operating"])
        out["states_with_processing_data"] = int(len(df))
        out["total_operating_factories"] = int(df["factories_operating"].sum())
    return out or None


def real_weather_for(start: date, days: int) -> dict[str, tuple[float | None, int]]:
    """Slice of the real weather table keyed by ISO date -> (temp_c, rain).

    Dates outside coverage are simply absent; the caller decides how to
    handle gaps (never invents values silently).
    """
    w = load_weather_table()
    if w.empty:
        return {}
    end = start + timedelta(days=days - 1)
    sel = w[(w["date"] >= pd.Timestamp(start)) & (w["date"] <= pd.Timestamp(end))]
    return {d.strftime("%Y-%m-%d"): (t, int(r))
            for d, t, r in zip(sel["date"], sel["temp_c"], sel["rain"])}


def context_status() -> dict:
    """Provenance snapshot for the dashboard Data tab."""
    w = load_weather_table()
    hol = load_india_holidays()
    shares = hces_category_value_shares()
    prov_path = DATA_DIR / "provenance" / "dataset_metadata.json"
    datasets = []
    if prov_path.exists():
        try:
            datasets = json.loads(prov_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    qr_path = DATA_DIR / "provenance" / "quality_reports.json"
    quality = {}
    if qr_path.exists():
        try:
            quality = json.loads(qr_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "weather_rows": int(len(w)),
        "weather_coverage": {
            "start": str(w["date"].min().date()) if len(w) else None,
            "end": str(w["date"].max().date()) if len(w) else None,
        },
        "holiday_count": len(hol),
        "hces_categories": len(shares),
        "datasets": datasets,
        "quality_reports": quality,
        "india_facts": {
            "latest_food_inflation": latest_food_inflation(),
            "waste_benchmark_unep": india_waste_facts(),
            "online_order_behaviour": demand_behaviour_facts(),
            "supply_references": supply_facts(),
        },
    }
