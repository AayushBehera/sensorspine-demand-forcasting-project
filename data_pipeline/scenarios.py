"""Deterministic redistribution-engine scenarios (SYNTHETIC, labelled).

Eleven fixed scenarios exercise every branch of the surplus->recommendation
pipeline. No randomness: every quantity is hand-set so failures are
debuggable and expectations are exact. Each scenario records
is_synthetic=true and its expectation; tests assert the engine honours it.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_thresholds
from app.data_generator import ITEMS, LOCATIONS, _distance
from app.recommend import build_recommendations

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "synthetic" / "operational" / "redistribution_scenarios.json"

CAT = {iid: cat for iid, _n, cat, _p in ITEMS}
SCENARIO_DATE = "2026-06-15"   # a Monday, mid-window
NOW = datetime(2026, 6, 15, 12, 30)   # lunch window open


def row(loc: str, item: str, period: str, demand: float, supply: float) -> dict:
    surplus = supply - demand
    if supply != supply or supply is None:
        status = "unknown_supply"
    elif surplus <= -0.10 * max(demand, 1):
        status = "shortage"
    elif surplus <= 0.05 * max(demand, 1):
        status = "balanced"
    elif surplus <= 0.20 * max(demand, 1):
        status = "low_surplus"
    else:
        status = "high_surplus"
    return {
        "date": SCENARIO_DATE, "location_id": loc, "item_id": item,
        "category": CAT[item], "meal_period": period,
        "predicted_demand": demand, "supply": supply,
        "supply_basis": "confirmed", "surplus": surplus, "status": status,
        "is_synthetic": True, "scenario": None,  # filled by builder
    }


def _frame(rows: list[dict], name: str) -> pd.DataFrame:
    for r in rows:
        r["scenario"] = name
    return pd.DataFrame(rows)


# --- scenarios -------------------------------------------------------------------

def normal_day() -> pd.DataFrame:
    """Balanced operations: small surpluses, small shortages, nothing actionable."""
    rows = [row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 100, 104),
            row("LOC-DIN-N", "ITM-RICE-BWL", "lunch", 80, 78),
            row("LOC-CAN-S", "ITM-PASTA", "lunch", 40, 41)]
    return _frame(rows, "normal_day")


def weekend() -> dict[str, pd.DataFrame]:
    """Weekend pattern baked into demand levels (sports canteen busy)."""
    busy = _frame([row("LOC-CAN-S", "ITM-RICE-BWL", "lunch", 90, 88)], "weekend_busy")
    quiet = _frame([row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 55, 57)], "weekend_quiet")
    return {"weekend_busy": busy, "weekend_quiet": quiet}


def holiday_closed() -> pd.DataFrame:
    """Real Indian public holiday: institutional demand collapses."""
    rows = [row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 35, 100),
            row("LOC-DIN-N", "ITM-RICE-BWL", "lunch", 28, 80)]
    return _frame(rows, "holiday_low_demand")


def festival_spike() -> pd.DataFrame:
    """Festival: demand spikes everywhere -> shortages, no usable surplus."""
    rows = [row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 180, 150),
            row("LOC-DIN-N", "ITM-RICE-BWL", "lunch", 140, 120)]
    return _frame(rows, "festival_spike")


def campus_event() -> pd.DataFrame:
    """Sports event at canteen: local spike while main hall over-catered."""
    rows = [row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 100, 160),   # big surplus
            row("LOC-CAN-S", "ITM-RICE-BWL", "lunch", 130, 60)]    # event shortage
    return _frame(rows, "campus_event")


def weather_disruption() -> pd.DataFrame:
    """Heavy monsoon rain: outdoor kiosk collapses, dining hall sheltered."""
    rows = [row("LOC-KIO-L", "ITM-RICE-BWL", "lunch", 8, 30),
            row("LOC-DIN-N", "ITM-RICE-BWL", "lunch", 95, 70)]
    return _frame(rows, "weather_disruption")


def overproduction() -> pd.DataFrame:
    """Everything over-produced, nowhere short: pure waste-risk picture."""
    rows = [row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 90, 170),
            row("LOC-DIN-N", "ITM-RICE-BWL", "lunch", 70, 110),
            row("LOC-CAN-S", "ITM-PASTA", "dinner", 30, 55)]
    return _frame(rows, "overproduction")


def shortage_everywhere() -> pd.DataFrame:
    """Under-production across the board: nothing to redistribute."""
    rows = [row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 150, 100),
            row("LOC-DIN-N", "ITM-RICE-BWL", "lunch", 120, 80)]
    return _frame(rows, "shortage_everywhere")


def redistribution_opportunity() -> pd.DataFrame:
    """Canonical case: one clear donor, one clear needy destination."""
    rows = [row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 80, 200),    # +120 surplus
            row("LOC-KIO-L", "ITM-RICE-BWL", "lunch", 45, 5)]      # -40 need
    return _frame(rows, "redistribution_opportunity")


def no_eligible_destination() -> pd.DataFrame:
    """Surplus exists but the only other location is closed/saturated."""
    rows = [row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 80, 200),
            row("LOC-DIN-N", "ITM-RICE-BWL", "dinner", 0, 0)]      # not operating lunch
    # make DIN-N absent from lunch entirely instead:
    f = _frame(rows[:1], "no_eligible_destination")
    return f


def multiple_candidates() -> pd.DataFrame:
    """One donor, two needy destinations competing for the same surplus."""
    rows = [row("LOC-CAF-M", "ITM-RICE-BWL", "lunch", 80, 220),    # +140 surplus
            row("LOC-DIN-N", "ITM-RICE-BWL", "lunch", 90, 20),     # need 70
            row("LOC-KIO-L", "ITM-RICE-BWL", "lunch", 50, 10)]     # need 40
    return _frame(rows, "multiple_candidates")


ALL = {
    "normal_day": normal_day,
    "weekend": lambda: weekend()["weekend_busy"],
    "weekend_quiet": lambda: weekend()["weekend_quiet"],
    "holiday_low_demand": holiday_closed,
    "festival_spike": festival_spike,
    "campus_event": campus_event,
    "weather_disruption": weather_disruption,
    "overproduction": overproduction,
    "shortage_everywhere": shortage_everywhere,
    "redistribution_opportunity": redistribution_opportunity,
    "no_eligible_destination": no_eligible_destination,
    "multiple_candidates": multiple_candidates,
}


def distances_frame() -> pd.DataFrame:
    locs = [l[0] for l in LOCATIONS]
    rows = [{"from_location": a, "to_location": b, "distance_km": _distance(a, b)}
            for a in locs for b in locs if a != b]
    return pd.DataFrame(rows)


def run_all() -> dict:
    th = get_thresholds()
    dist = distances_frame()
    results: dict[str, dict] = {}
    combined: list[pd.DataFrame] = []
    for name, fn in ALL.items():
        assessment = fn()
        recs = build_recommendations(assessment, dist, th, now=NOW)
        results[name] = {
            "series": int(len(assessment)),
            "high_surplus_series": int((assessment["status"] == "high_surplus").sum()),
            "shortage_series": int((assessment["status"] == "shortage").sum()),
            "recommendations": len(recs),
            "top_score": recs[0]["score"] if recs else None,
            "total_transferable_units": round(sum(r["transfer_quantity"]
                                                  for r in recs), 1),
            "is_synthetic": True,
        }
        assessment = assessment.copy()
        assessment["simulation_scenario"] = name
        combined.append(assessment)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(combined, ignore_index=True).to_csv(
        OUT.with_suffix(".csv"), index=False)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {len(results)} scenarios -> {OUT.name}")
    for name, r in results.items():
        print(f"  {name:28s} recs={r['recommendations']} "
              f"top={r['top_score']} units={r['total_transferable_units']}")
    return results


if __name__ == "__main__":
    run_all()
