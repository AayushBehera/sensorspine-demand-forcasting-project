"""Reproducible SYNTHETIC operational dataset, driven by REAL India context.

This is reference/evaluation data, clearly labelled as synthetic until a live
POS/transaction feed is connected. It mimics
realistic campus food-service behaviour: weekday rhythms, term/exam
calendars, holidays, promotions, weather effects, and planner behaviour
(EWMA-based production planning) that naturally produces surpluses and
shortages. Run scripts/run_pipeline.py or POST /api/data/generate to build it.

Context realism (the only non-synthetic inputs):
  * WEATHER  - real Bengaluru ERA5 daily data (Open-Meteo) when available;
               missing days fall back to the synthetic seasonal model and
               are reported in `context_provenance`.
  * HOLIDAYS - real Indian public-holiday calendar (`holidays` package).
The academic calendar (terms/exams) remains synthetic - no real campus
calendar exists in this prototype.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import DATA_DIR, RAW_DATA_CSV
from .india_context import load_india_holidays, real_weather_for

LOCATIONS = [
    # id, name, scale (relative size), active meal periods, role hint
    ("LOC-CAF-M", "Main Cafeteria",      1.00, ["breakfast", "lunch", "dinner"], "large dining hall"),
    ("LOC-DIN-N", "North Dining Hall",   0.80, ["breakfast", "lunch", "dinner"], "large dining hall"),
    ("LOC-CAN-S", "Sports Canteen",      0.45, ["lunch", "dinner"],              "event-driven canteen"),
    ("LOC-OUT-C", "Campus Outlet C",     0.30, ["lunch"],                        "small grab-and-go outlet"),
    ("LOC-KIO-L", "Library Kiosk",       0.20, ["lunch"],                        "small kiosk"),
]

ITEMS = [
    # id, name, category, popularity multiplier by period
    ("ITM-VEG-SAND", "Veg Sandwich",    "bakery",    {"breakfast": 0.9, "lunch": 1.0, "dinner": 0.4}),
    ("ITM-CHKN-WRAP", "Chicken Wrap",   "bakery",    {"breakfast": 0.6, "lunch": 1.0, "dinner": 0.5}),
    ("ITM-PASTA",    "Pasta Primavera", "hot_meal",  {"breakfast": 0.1, "lunch": 1.0, "dinner": 0.9}),
    ("ITM-RICE-BWL", "Rice Bowl",       "hot_meal",  {"breakfast": 0.1, "lunch": 0.9, "dinner": 1.0}),
    ("ITM-SALAD",    "Garden Salad",    "cold_item", {"breakfast": 0.3, "lunch": 1.0, "dinner": 0.5}),
    ("ITM-COFFEE",   "Brewed Coffee",   "beverage",  {"breakfast": 1.2, "lunch": 0.7, "dinner": 0.2}),
]

# Pairwise distances in km between locations (reference logistics data).
DISTANCES_KM = {
    ("LOC-CAF-M", "LOC-DIN-N"): 0.6,
    ("LOC-CAF-M", "LOC-CAN-S"): 1.8,
    ("LOC-CAF-M", "LOC-OUT-C"): 0.9,
    ("LOC-CAF-M", "LOC-KIO-L"): 1.4,
    ("LOC-DIN-N", "LOC-CAN-S"): 2.2,
    ("LOC-DIN-N", "LOC-OUT-C"): 1.1,
    ("LOC-DIN-N", "LOC-KIO-L"): 0.7,
    ("LOC-CAN-S", "LOC-OUT-C"): 2.6,
    ("LOC-CAN-S", "LOC-KIO-L"): 2.9,
    ("LOC-OUT-C", "LOC-KIO-L"): 1.5,
}


def _distance(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return DISTANCES_KM.get((a, b), DISTANCES_KM.get((b, a), 5.0))


def generate_context(start: date, days: int, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Returns (weather_df, context_events_df, provenance) for the date range.

    Weather prefers REAL Bengaluru ERA5 rows; gaps use the synthetic
    seasonal model (flagged per-date). Holidays are the REAL Indian
    public calendar; term/exam events remain synthetic.
    """
    dates = [start + timedelta(days=i) for i in range(days)]
    t = np.arange(days)
    real = real_weather_for(start, days)

    temps: list[float | None] = []
    rains: list[int] = []
    sources: list[str] = []
    n_real = 0
    for i, d in enumerate(dates):
        ds = d.isoformat()
        if ds in real:
            temp, rain = real[ds]
            if temp is not None:
                temps.append(temp)
                rains.append(rain)
                sources.append("era5_bengaluru_real")
                n_real += 1
                continue
        # synthetic seasonal fallback for missing days
        temps.append(round(18 + 8 * math.sin(2 * math.pi * (i / 90)) + float(rng.normal(0, 2.0)), 1))
        rains.append(int(rng.random() < 0.25 + 0.1 * math.sin(2 * math.pi * (i / 45))))
        sources.append("synthetic_fallback")

    weather = pd.DataFrame({"date": [d.isoformat() for d in dates],
                            "temp_c": temps,
                            "rain": rains,
                            "source": sources})
    prov = {
        "weather_real_rows": n_real,
        "weather_synthetic_rows": days - n_real,
        "weather_source": "Open-Meteo ERA5 Bengaluru + synthetic gap-fill",
        "holiday_source": "`holidays` package - India (official calendars)",
    }

    events: list[tuple[str, str, str]] = []
    india_holidays = load_india_holidays()
    prov["holidays_matched"] = sum(1 for d in dates if d.isoformat() in india_holidays)
    # Academic calendar anchored to the window: term starts at window start,
    # two mid-term breaks, exams in the final 10 days. SYNTHETIC by design.
    for i, d in enumerate(dates):
        if i < 5:
            events.append((d.isoformat(), "term_start", "higher_footfall"))
        elif 60 <= i < 66 or 130 <= i < 136:
            events.append((d.isoformat(), "mid_term_break", "lower_footfall"))
        elif i >= days - 10:
            events.append((d.isoformat(), "exams", "late_night_shift"))
        if d.isoformat() in india_holidays:
            events.append((d.isoformat(), "public_holiday", "campus_closed_low"))

    ctx = pd.DataFrame(events, columns=["date", "event_type", "effect_hint"])
    return weather, ctx, prov


def generate(start: date | None = None, days: int = 180, seed: int = 42,
             out_dir=DATA_DIR) -> dict[str, pd.DataFrame]:
    """Generate the full synthetic dataset and write raw CSVs to out_dir."""
    rng = np.random.default_rng(seed)
    if start is None:
        start = date.today() - timedelta(days=days)

    weather, ctx, ctx_prov = generate_context(start, days, rng)
    weather_by_date = {r["date"]: r for _, r in weather.iterrows()}
    events_by_date: dict[str, set[str]] = {}
    for _, r in ctx.iterrows():
        events_by_date.setdefault(r["date"], set()).add(r["event_type"])

    # Promotions: ~10% of (date,item) pairs.
    promo_pairs: set[tuple[str, str]] = set()
    for item in ITEMS:
        item_id = item[0]
        for d_i in rng.choice(days, size=max(1, days // 10), replace=False):
            promo_pairs.add(((start + timedelta(days=int(d_i))).isoformat(), item_id))

    rows: list[dict] = []
    # Planner state: EWMA of observed demand per (loc, item, period).
    ewma: dict[tuple[str, str, str], float] = {}

    for di in range(days):
        d = start + timedelta(days=di)
        ds = d.isoformat()
        wrow = weather_by_date[ds]
        evts = events_by_date.get(ds, set())
        is_weekend = d.weekday() >= 5
        is_holiday = "public_holiday" in evts
        is_break = "mid_term_break" in evts
        is_term_start = "term_start" in evts
        is_exams = "exams" in evts

        cal_factor = 1.0
        if is_holiday:
            cal_factor *= 0.35
        if is_break:
            cal_factor *= 0.55
        if is_term_start:
            cal_factor *= 1.15
        if is_exams:
            cal_factor *= 1.05

        for loc_id, _lname, loc_scale, periods, _role in LOCATIONS:
            # Weekend behaviour: main halls quieter, sports canteen busier.
            if is_weekend:
                lf = 1.35 if loc_id == "LOC-CAN-S" else 0.55
            else:
                lf = 1.0
            for item_id, _iname, cat, pop in ITEMS:
                for period in periods:
                    base = 120.0 * loc_scale * pop[period]
                    if base < 3:
                        continue
                    wf = 1.0
                    if wrow["rain"]:
                        wf *= 0.92 if cat != "beverage" else 1.05
                    if not is_holiday and wrow["temp_c"] > 26:
                        wf *= 1.10 if cat in ("cold_item", "beverage") else 0.95
                    promo = (ds, item_id) in promo_pairs
                    if promo:
                        wf *= 1.22
                    demand = base * cal_factor * lf * wf
                    demand *= float(rng.lognormal(mean=0.0, sigma=0.13))
                    if loc_id == "LOC-CAN-S" and rng.random() < 0.04:
                        demand *= float(rng.uniform(1.5, 2.2))  # sports event spike
                    demand = max(0.0, round(demand))
                    demand = int(demand)

                    key = (loc_id, item_id, period)
                    prev = ewma.get(key)
                    if prev is None:
                        plan_raw = demand * float(rng.uniform(0.9, 1.15))
                    else:
                        plan_raw = prev * float(rng.uniform(1.02, 1.18))  # safety buffer
                    planned = max(0, int(math.ceil(plan_raw)))
                    ewma[key] = 0.7 * (prev if prev is not None else demand) + 0.3 * demand

                    rows.append({
                        "date": ds,
                        "location_id": loc_id,
                        "item_id": item_id,
                        "category": cat,
                        "meal_period": period,
                        "planned_production": planned,
                        "actual_demand": demand,
                        "promotion": int(promo),
                        "is_synthetic": True,
                    })

    services = pd.DataFrame(rows)
    services["synthetic_generator_version"] = "2.0-india-context"
    services["simulation_scenario"] = "campus_baseline"

    out_dir.mkdir(parents=True, exist_ok=True)
    services.to_csv(out_dir / RAW_DATA_CSV.name, index=False)
    weather.to_csv(out_dir / "weather.csv", index=False)
    ctx.to_csv(out_dir / "context_events.csv", index=False)
    (out_dir / "context_provenance.json").write_text(
        json.dumps({**ctx_prov,
                    "transactions_source": "SYNTHETIC operational simulator "
                                           "(no real campus POS data exists)",
                    "generation_seed": seed, "days": days},
                   indent=2),
        encoding="utf-8")
    pd.DataFrame(
        [(a, b, _distance(a, b)) for a, *_ in LOCATIONS for b, *__ in LOCATIONS if a != b],
        columns=["from_location", "to_location", "distance_km"],
    ).to_csv(out_dir / "distances.csv", index=False)
    return {
        "services": services,
        "weather": weather,
        "context_events": ctx,
        "context_provenance": ctx_prov,
    }


if __name__ == "__main__":
    frames = generate()
    s = frames["services"]
    print(f"synthetic dataset written: {len(s):,} service records, "
          f"{s['actual_demand'].sum():,} units demanded")
    print("context:", frames["context_provenance"])
