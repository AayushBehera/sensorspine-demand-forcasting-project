"""Backend tools the chat engine can call.

Each tool is a plain Python function returning a normalized dict ("observation").
The deterministic fallback and the real LLM providers both call through
`run_tool`. The tool specs double as the function-calling schema for an LLM.
"""
from __future__ import annotations

from datetime import date, timedelta

import app.service as svc
import app.insights as ins
from app import weather

# --- helpers -----------------------------------------------------------------

def _range(days: int) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=max(1, int(days)))
    return start.isoformat(), end.isoformat()


# --- tool implementations ----------------------------------------------------

def demand_summary(days: int = 30, location_id: str | None = None,
                   category: str | None = None,
                   meal_period: str | None = None) -> dict:
    a = svc.analytics_summary(days=days, location_id=location_id,
                              category=category, meal_period=meal_period)
    a["_tool"] = "demand_summary"
    return a


def forecasts(days: int = 30, location_id: str | None = None,
              item_id: str | None = None,
              meal_period: str | None = None) -> dict:
    start, end = _range(days)
    rows = svc.list_forecasts(start=start, end=end, location_id=location_id,
                              item_id=item_id, meal_period=meal_period,
                              page_size=500).get("items", [])
    return {"rows": rows, "window": {"start": start, "end": end},
            "_tool": "forecasts"}


def surplus(days: int = 30, location_id: str | None = None) -> dict:
    start, end = _range(days)
    rows = svc.list_surplus_history(start=start, end=end,
                                    location_id=location_id,
                                    page_size=2000).get("items", [])
    return {"rows": rows, "window": {"start": start, "end": end},
            "_tool": "surplus"}


def redistribution(status: str | None = None,
                   location_id: str | None = None) -> dict:
    rows = svc.list_recommendations(status=status, location_id=location_id,
                                    limit=500)
    return {"rows": rows, "_tool": "redistribution"}


def outcomes(days: int = 30, location_id: str | None = None,
             source: str | None = None) -> dict:
    start, end = _range(days)
    rows = svc.list_outcomes(start=start, end=end, location_id=location_id,
                             source=source, page_size=500).get("items", [])
    return {"rows": rows, "_tool": "outcomes"}


def supply_plans(days: int = 30, location_id: str | None = None) -> dict:
    start, end = _range(days)
    rows = svc.list_supply_plans(start=start, end=end,
                                 location_id=location_id,
                                 page_size=500).get("items", [])
    return {"rows": rows, "_tool": "supply_plans"}


def food_context() -> dict:
    c = ins.india_context_charts()
    c["_tool"] = "food_context"
    return c


def geographic() -> dict:
    return {"campus_map": ins.campus_map(),
            "bengaluru_map": ins.bengaluru_demand_map(),
            "_tool": "geographic"}


def weather_now(location_id: str | None = None, days: int = 7) -> dict:
    w = weather.get_weather(location_id=location_id, days=days)
    w["_tool"] = "weather_now"
    return w


def data_records(days: int = 30, location_id: str | None = None,
                 item_id: str | None = None, category: str | None = None,
                 meal_period: str | None = None, search: str | None = None,
                 page: int = 1) -> dict:
    start, end = _range(days)
    r = svc.data_records(start=start, end=end, location_id=location_id,
                         item_id=item_id, category=category,
                         meal_period=meal_period, search=search, page=page,
                         page_size=200)
    r["_tool"] = "data_records"
    return r


def overview(days: int = 30, location_id: str | None = None,
             category: str | None = None,
             meal_period: str | None = None) -> dict:
    o = ins.overview(days=days, location_id=location_id, category=category,
                     meal_period=meal_period)
    o["_tool"] = "overview"
    return o


def model_perf() -> dict:
    a = svc.analytics_summary(days=30)
    a["_tool"] = "model_perf"
    return a


# --- registry ----------------------------------------------------------------

TOOLS: list[dict] = [
    {"name": "demand_summary", "fn": demand_summary,
     "description": "Aggregate demand, waste and accuracy KPIs over a window.",
     "params": {"days": "int (7-180)", "location_id": "str?", "category": "str?",
                "meal_period": "str?"}},
    {"name": "forecasts", "fn": forecasts,
     "description": "Forecast vs actual records for a window.",
     "params": {"days": "int", "location_id": "str?", "item_id": "str?",
                "meal_period": "str?"}},
    {"name": "surplus", "fn": surplus,
     "description": "Surplus/shortage assessments over a window.",
     "params": {"days": "int", "location_id": "str?"}},
    {"name": "redistribution", "fn": redistribution,
     "description": "Transfer recommendations (pending/accepted/rejected).",
     "params": {"status": "str?", "location_id": "str?"}},
    {"name": "outcomes", "fn": outcomes,
     "description": "Realized outcomes (recorded vs forecast).",
     "params": {"days": "int", "location_id": "str?", "source": "str?"}},
    {"name": "supply_plans", "fn": supply_plans,
     "description": "Operator-posted supply plans.",
     "params": {"days": "int", "location_id": "str?"}},
    {"name": "food_context", "fn": food_context,
     "description": "India food context: HCES shares, IFCT nutrition, inflation, crops.",
     "params": {}},
    {"name": "geographic", "fn": geographic,
     "description": "Campus map and Bengaluru survey demand points.",
     "params": {}},
    {"name": "weather_now", "fn": weather_now,
     "description": "Live Open-Meteo weather for a campus (defaults to metro centre).",
     "params": {"location_id": "str?", "days": "int (1-14)"}},
    {"name": "data_records", "fn": data_records,
     "description": "Row-level explorer over the validated dataset.",
     "params": {"days": "int", "location_id": "str?", "item_id": "str?",
                "category": "str?", "meal_period": "str?", "search": "str?"}},
    {"name": "overview", "fn": overview,
     "description": "Full overview payload: demand by day/location/item/meal/category, waste, weather.",
     "params": {"days": "int", "location_id": "str?", "category": "str?",
                "meal_period": "str?"}},
    {"name": "model_perf", "fn": model_perf,
     "description": "Model feedback metrics and registry.",
     "params": {}},
]

_BY_NAME = {t["name"]: t for t in TOOLS}


def run_tool(name: str, args: dict | None = None) -> dict:
    tool = _BY_NAME.get(name)
    if not tool:
        return {"_tool": name, "error": f"unknown tool {name}"}
    args = args or {}
    try:
        return tool["fn"](**args)
    except TypeError as e:
        return {"_tool": name, "error": f"bad args: {e}"}
