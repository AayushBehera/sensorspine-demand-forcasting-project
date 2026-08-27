"""Dashboard insight aggregates: full-window, accurate representations.

Every function reads the validated clean frame / processed reference data and
returns JSON-safe dicts. No sampling shortcuts: charts cover the whole
operational window unless a shorter window is explicitly requested.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import DATA_DIR
from . import db, service

PROCESSED = DATA_DIR / "processed"


def _clean() -> pd.DataFrame:
    return service.get_clean()


# --- operational aggregates -----------------------------------------------------

def overview(days: int | None = None, location_id: str | None = None,
             category: str | None = None,
             meal_period: str | None = None) -> dict:
    """Everything the dashboard's chart tabs need, in one payload.

    location_id/category/meal_period pre-filter the operational-record
    aggregates; weather/context payloads stay global.
    """
    clean = _clean()
    if days:
        clean = clean[clean["date"] > clean["date"].max() - pd.Timedelta(days=days)]
    if location_id:
        clean = clean[clean["location_id"] == location_id]
    if category:
        clean = clean[clean["category"] == category]
    if meal_period:
        clean = clean[clean["meal_period"] == meal_period]

    clean = clean.copy()
    clean["waste_units"] = (clean["planned_production"]
                            - clean["actual_demand"]).clip(lower=0)

    by_day_loc = (clean.pivot_table(index=clean["date"].dt.strftime("%Y-%m-%d"),
                                    columns="location_id",
                                    values="actual_demand", aggfunc="sum")
                  .fillna(0.0).round(1))
    by_item = (clean.groupby("item_id")["actual_demand"].sum()
               .sort_values(ascending=False).round(0))
    by_meal = clean.groupby("meal_period")["actual_demand"].sum().round(0)
    by_cat = clean.groupby("category")["actual_demand"].sum().round(0)
    waste_by_item = (clean.groupby("item_id")["waste_units"].sum()
                     .sort_values(ascending=False).round(0))
    daily_total = clean.groupby(clean["date"].dt.strftime("%Y-%m-%d"))[
        "actual_demand"].sum().round(1)
    rain = clean.assign(rainy=clean["rain"].astype(bool))
    rain_cmp = {
        "rainy_avg": round(float(rain[rain.rainy].groupby("date")[
            "actual_demand"].sum().mean()), 1),
        "dry_avg": round(float(rain[~rain.rainy].groupby("date")[
            "actual_demand"].sum().mean()), 1),
    }

    weather = (pd.read_csv(DATA_DIR / "weather.csv")
               if (DATA_DIR / "weather.csv").exists() else pd.DataFrame())
    events = (pd.read_csv(DATA_DIR / "context_events.csv")
              if (DATA_DIR / "context_events.csv").exists() else pd.DataFrame())

    conn = db.connect(service.DB_PATH)
    try:
        latest = db.latest_model_version(conn)
        feedback = db.feedback_metrics(conn, model_version=latest)
        registry = [dict(r) for r in conn.execute(
            "SELECT * FROM model_registry ORDER BY trained_at DESC LIMIT 5")]
    finally:
        conn.close()

    return {
        "window": {"start": str(clean["date"].min().date()),
                   "end": str(clean["date"].max().date()),
                   "rows": int(len(clean))},
        "demand_by_day_location": {
            "dates": list(by_day_loc.index),
            "series": {c: list(by_day_loc[c]) for c in by_day_loc.columns}},
        "daily_total_demand": dict(daily_total),
        "demand_by_item": dict(by_item),
        "waste_by_item": dict(waste_by_item),
        "demand_by_meal": dict(by_meal),
        "demand_by_category": dict(by_cat),
        "rain_vs_dry_daily_avg": rain_cmp,
        "weather": {"dates": list(weather.get("date", [])),
                    "temp_c": list(weather.get("temp_c", [])),
                    "rain": list(weather.get("rain", []))},
        "context_events": events.to_dict(orient="records") if len(events) else [],
        "feedback_metrics": feedback,
        "model_registry": registry,
        "model_version": latest,
    }


def campus_map() -> dict:
    """Campus locations as a distance-true map (classical MDS to 2-D)."""
    import numpy as np

    dist = pd.read_csv(DATA_DIR / "distances.csv")
    locs = sorted(set(dist["from_location"]) | set(dist["to_location"]))
    idx = {l: i for i, l in enumerate(locs)}
    D = np.full((len(locs), len(locs)), np.nan)
    for _, r in dist.iterrows():
        D[idx[r["from_location"]], idx[r["to_location"]]] = r["distance_km"]
        D[idx[r["to_location"]], idx[r["from_location"]]] = r["distance_km"]
    np.fill_diagonal(D, 0.0)
    # mean-impute any gap so MDS stays stable
    mean_km = float(np.nanmean(D[D > 0])) if (D > 0).any() else 1.0
    D = np.where(np.isnan(D), mean_km, D)

    # classical MDS: J = I - 11'/n ; B = -0.5 J D^2 J ; top-2 eigvecs
    n = len(locs)
    J = np.eye(n) - np.ones((n, n)) / n
    B = -0.5 * J @ (D ** 2) @ J
    vals, vecs = np.linalg.eigh(B)
    order = np.argsort(vals)[::-1][:2]
    pts = vecs[:, order] * np.sqrt(np.maximum(vals[order], 0))

    clean = _clean()
    demand = clean.groupby("location_id")["actual_demand"].sum()

    names = {l["location_id"]: l["name"] for l in service.LOCATIONS_REF}
    edges = [{"from": r["from_location"], "to": r["to_location"],
              "km": float(r["distance_km"])} for _, r in dist.iterrows()]
    return {
        "nodes": [{"id": l, "name": names.get(l, l),
                   "x": round(float(pts[i, 0]), 4),
                   "y": round(float(pts[i, 1]), 4),
                   "demand_units": round(float(demand.get(l, 0.0)), 0)}
                  for i, l in enumerate(locs)],
        "edges": edges,
    }


def bengaluru_demand_map() -> dict:
    """Survey respondents as a geo scatter (real lat/lng from the dataset)."""
    p = PROCESSED / "restaurant" / "online_food_orders_bangalore.csv"
    if not p.exists():
        return {"points": [], "summary": {}}
    df = pd.read_csv(p)
    pts = (df.groupby(["latitude", "longitude"], as_index=False)
           .agg(n=("ordered_online", "size"),
                ordered=("ordered_online", "sum")))
    pts["ordered"] = pts["ordered"].astype(float)
    return {
        "points": [
            {"lat": float(r.latitude), "lng": float(r.longitude),
             "n": int(r.n), "ordered": int(r.ordered)}
            for r in pts.itertuples()],
        "summary": {
            "respondents": int(len(df)),
            "order_rate_pct": round(100 * df["ordered_online"].mean(), 1),
            "by_occupation": {k: round(v, 3) for k, v in
                              df.groupby("occupation")["ordered_online"].mean()
                              .astype(float).items()},
            "by_income": {k: round(v, 3) for k, v in
                          df.groupby("monthly_income")["ordered_online"].mean()
                          .astype(float).items()},
        },
    }


# --- India context layer ---------------------------------------------------------

def india_context_charts() -> dict:
    out: dict = {}

    p = PROCESSED / "consumption" / "hces_bengaluru_category_shares.csv"
    if p.exists():
        df = pd.read_csv(p)
        out["hces_value_shares"] = [
            {"category": r.food_category, "share_pct": round(float(r.value_share_pct), 2)}
            for r in df.sort_values("value_share_pct", ascending=False).itertuples()]

    p = PROCESSED / "consumption" / "hces_factsheet_mpce_trend_tidy.csv"
    if p.exists():
        df = pd.read_csv(p)
        df = df[(df["factsheet_table"] == "%CompositionMPCE")
                & (df["Item"] == "Food")]
        rural_col = "Rural India-Without Imputation"
        urban_col = "Urban India-Without Imputation"
        rows = []
        for _, r in df.iterrows():
            rural, urban = _f(r.get(rural_col)), _f(r.get(urban_col))
            if rural is None and urban is None:
                continue
            rows.append({"year": r["Year"], "rural": rural, "urban": urban})
        # one row per survey year
        seen, dedup = set(), []
        for r in rows:
            if r["year"] not in seen:
                seen.add(r["year"])
                dedup.append(r)
        out["food_share_of_mpce_trend"] = dedup

    p = PROCESSED / "context" / "india_food_inflation_monthly.csv"
    if p.exists():
        df = pd.read_csv(p)
        df["label"] = df["month"].str[:3] + " " + df["year"].astype(str)
        out["food_inflation_monthly"] = [
            {"label": r.label, "inflation_pct": float(r.inflation_pct)}
            for r in df.itertuples()]

    p = PROCESSED / "waste" / "unep_india_food_waste.csv"
    if p.exists():
        df = pd.read_csv(p)
        out["unep_india_waste"] = [
            {"year": int(r.year), "retail": float(r.retail_kg_per_capita),
             "out_of_home": float(r.out_of_home_kg_per_capita),
             "household": float(r.household_kg_per_capita)}
            for r in df.itertuples()]

    p = PROCESSED / "supply" / "crop_production_national.csv"
    if p.exists():
        df = pd.read_csv(p).head(10)
        out["crop_production_mt"] = [
            {"crop": r.crop, "production_mt": float(r.production_mt)}
            for r in df.itertuples()]

    p = PROCESSED / "institutional" / "food_processing_capacity_by_state.csv"
    if p.exists():
        df = pd.read_csv(p).sort_values("factories_operating", ascending=False).head(12)
        out["processing_capacity_top_states"] = [
            {"state": r.state_ut, "registered": int(r.factories_registered),
             "operating": int(r.factories_operating)}
            for r in df.itertuples()]

    p = PROCESSED / "context" / "india_public_holidays.csv"
    if p.exists():
        hol = pd.read_csv(p)
        hol = hol[hol["date"] >= str(pd.Timestamp.today().date())].head(8)
        out["upcoming_holidays"] = [
            {"date": r.date, "name": r.name} for r in hol.itertuples()]

    p = PROCESSED / "restaurant" / "swiggy_cuisine_frequencies.csv"
    if p.exists():
        df = pd.read_csv(p)
        df = df[df["category_or_unmapped"] != "unmapped"]
        top = df.groupby("category_or_unmapped")["count"].sum().sort_values(
            ascending=False).head(8)
        out["swiggy_category_counts"] = [
            {"category": k, "count": int(v)} for k, v in top.items()]

    return out


def _f(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None
