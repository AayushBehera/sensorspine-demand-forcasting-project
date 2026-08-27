"""FastAPI application exposing the Forecast-to-Action platform.

Contract notes:
  * All business logic lives in service.py / domain modules.
  * Errors are structured JSON: {"error": <code>, "detail": <human text>}.
  * If env FSDB_API_KEY is set, every /api/* call must send header
    'X-API-Key' (secure-by-default when deployed; unset = open local
    development mode only).
"""
from __future__ import annotations

import logging
import os

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import chat, db, insights, service
from .config import DB_PATH, LOG_LEVEL, WEB_DIR, get_thresholds
from .surplus import STATUS_LABELS

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("sensorspine.api")

app = FastAPI(
    title="Sensorspine - Food Service Demand & Surplus Platform",
    version="1.0.0",
    description="Demand forecasting -> surplus risk -> redistribution "
                "recommendations. Operational records are labelled synthetic "
                "(is_synthetic=true) until live feeds are connected; the "
                "India context layer is real.",
)

API_KEY = os.environ.get("FSDB_API_KEY")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    conn = db.connect(DB_PATH)
    try:
        db.upsert_reference(conn, service.LOCATIONS_REF, service.ITEMS_REF)
        conn.commit()
    finally:
        conn.close()
    log.info("database ready at %s", DB_PATH)


def _guard(x_api_key: str | None) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail={
            "error": "unauthorized", "detail": "missing or invalid X-API-Key"})


def _http_error(exc: Exception, code: str, status: int = 400) -> HTTPException:
    log.warning("%s: %s", code, exc)
    return HTTPException(status_code=status,
                         detail={"error": code, "detail": str(exc)})


# --- Schemas -------------------------------------------------------------------

class DayRunRequest(BaseModel):
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    planned_promotions: dict[str, int] | None = None


class DecisionRequest(BaseModel):
    action: str = Field(pattern="^(accepted|rejected)$")
    units_moved: float | None = Field(None, ge=0)
    note: str | None = None


class ManualOutcome(BaseModel):
    service_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    location_id: str
    item_id: str
    meal_period: str = Field(pattern="^(breakfast|lunch|dinner)$")
    actual_demand: float = Field(ge=0)


class SupplyPlan(BaseModel):
    service_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    location_id: str
    item_id: str
    meal_period: str
    supply: float = Field(ge=0)


class ThresholdUpdate(BaseModel):
    thresholds: dict = Field(min_length=1)


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    log.exception("unhandled error")
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={
        "detail": {"error": "internal_error",
                   "detail": f"{type(exc).__name__}; see server logs"}})


# --- Health & meta --------------------------------------------------------------

@app.get("/api/health")
def health(x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    checks: dict = {"database": False, "raw_data": False,
                    "clean_data": False, "model": False}
    try:
        conn = db.connect(DB_PATH)
        conn.execute("SELECT 1 FROM forecasts LIMIT 1")
        checks["database"] = True
        conn.close()
    except Exception:
        pass
    checks["raw_data"] = service.RAW_DATA_CSV.exists()
    checks["clean_data"] = service.CLEAN_DATA_CSV.exists()
    artifact = service.load_artifact()
    checks["model"] = artifact is not None
    return {"status": "ok" if all(checks.values()) else "degraded",
            "checks": checks}


@app.get("/api/data/sources")
def data_sources(x_api_key: str | None = Header(default=None)):
    """Provenance of every integrated dataset (REAL vs SYNTHETIC, honest)."""
    _guard(x_api_key)
    try:
        from .india_context import context_status
        return context_status()
    except Exception as exc:
        raise _http_error(exc, "data_sources_failed", 500)


@app.get("/api/meta")
def meta(x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    clean = service.get_clean()
    conn = db.connect(DB_PATH)
    try:
        ref = db.get_reference(conn)
        model_version = db.latest_model_version(conn)
    finally:
        conn.close()
    return {
        "locations": ref["locations"], "items": ref["items"],
        "status_labels": STATUS_LABELS,
        "model_version": model_version,
        "data_end_date": str(clean["date"].max().date()),
        "next_service_dates": service.next_service_dates(3),
        "synthetic_data": True,
        "context_provenance": service.last_context_provenance(),
    }


# --- Data lifecycle -------------------------------------------------------------

@app.post("/api/data/generate")
def generate_data(seed: int = Query(42), days: int = Query(180, ge=14, le=730),
                  x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    try:
        info = service.regenerate_data(seed, days)
        report = service.run_validation()
        return {"generated": info, "validation_report": report}
    except Exception as exc:
        raise _http_error(exc, "data_generation_failed", 500)


@app.post("/api/data/validate")
def validate_data(x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    try:
        return service.run_validation()
    except FileNotFoundError as exc:
        raise _http_error(exc, "data_missing", 409)


# --- Model ----------------------------------------------------------------------

@app.post("/api/model/train")
def train_model(x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    try:
        summary = service.train_pipeline()
        return summary
    except Exception as exc:
        raise _http_error(exc, "training_failed", 500)


# --- The daily loop --------------------------------------------------------------

@app.post("/api/day/run")
def run_day(req: DayRunRequest = Body(default=DayRunRequest()),
            x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    dates = [req.date] if req.date else service.next_service_dates(1)
    try:
        return service.run_day(dates, planned_promotions=req.planned_promotions)
    except FileNotFoundError as exc:
        raise _http_error(exc, "data_missing", 409)
    except RuntimeError as exc:
        raise _http_error(exc, "model_unavailable", 409)


@app.get("/api/recommendations")
def list_recommendations(date: str | None = Query(None),
                         status: str | None = Query(None),
                         limit: int = Query(50, le=500),
                         x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    conn = db.connect(DB_PATH)
    try:
        q = "SELECT * FROM recommendations WHERE 1=1"
        params: list = []
        if date:
            q += " AND service_date=?"; params.append(date)
        if status:
            q += " AND status=?"; params.append(status)
        q += " ORDER BY score DESC LIMIT ?"; params.append(limit)
        rows = [dict(r) for r in conn.execute(q, params)]
        for r in rows:
            r["factors"] = __import__("json").loads(r.pop("factors_json") or "{}")
        return {"recommendations": rows, "count": len(rows)}
    finally:
        conn.close()


@app.post("/api/recommendations/{rec_id}/decision")
def decide(rec_id: int, req: DecisionRequest,
           x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    conn = db.connect(DB_PATH)
    try:
        ok = db.decide_recommendation(conn, rec_id, req.action,
                                      req.units_moved, req.note)
        conn.commit()
        if not ok:
            raise _http_error(
                ValueError(f"recommendation {rec_id} not found or already decided"),
                "not_decidable", 404)
        return {"recommendation_id": rec_id, "status": req.action}
    finally:
        conn.close()


@app.post("/api/outcomes/sync")
def outcomes_sync(x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    try:
        stats = service.sync_outcomes()
        conn = db.connect(DB_PATH)
        try:
            return {**stats, "feedback_metrics": db.feedback_metrics(
                conn, model_version=db.latest_model_version(conn))}
        finally:
            conn.close()
    except Exception as exc:
        raise _http_error(exc, "outcome_sync_failed", 500)


@app.post("/api/backtest/simulate")
def backtest(days: int = Query(14, ge=1, le=60),
             x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    try:
        return service.simulate_backtest(days)
    except Exception as exc:
        raise _http_error(exc, "backtest_failed", 500)


@app.post("/api/outcomes/manual")
def outcome_manual(o: ManualOutcome,
                   x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    n = service.record_manual_outcome(o.service_date, o.location_id, o.item_id,
                                      o.meal_period, o.actual_demand)
    return {"recorded": bool(n), **o.model_dump()}


@app.post("/api/supply-plans")
def post_plans(plans: list[SupplyPlan],
               x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    conn = db.connect(DB_PATH)
    try:
        n = db.post_supply_plans(conn, [p.model_dump() for p in plans])
        conn.commit()
        return {"plans_stored": n}
    finally:
        conn.close()


# --- Read endpoints (paginated) --------------------------------------------------

@app.get("/api/forecasts")
def list_forecasts_ep(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                      end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                      location_id: str | None = Query(None),
                      item_id: str | None = Query(None),
                      meal_period: str | None = Query(None),
                      model_version: str | None = Query(None),
                      page: int = Query(1, ge=1),
                      page_size: int = Query(200, ge=1, le=1000),
                      x_api_key: str | None = Header(default=None)):
    """Stored forecasts, newest service_date first."""
    _guard(x_api_key)
    return service.list_forecasts(start=start, end=end,
                                  location_id=location_id, item_id=item_id,
                                  meal_period=meal_period,
                                  model_version=model_version,
                                  page=page, page_size=page_size)


@app.get("/api/surplus/history")
def surplus_history_ep(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                       end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                       location_id: str | None = Query(None),
                       item_id: str | None = Query(None),
                       status: str | None = Query(None),
                       page: int = Query(1, ge=1),
                       page_size: int = Query(200, ge=1, le=1000),
                       x_api_key: str | None = Header(default=None)):
    """Stored surplus assessments, newest service_date first."""
    _guard(x_api_key)
    return service.list_surplus_history(start=start, end=end,
                                        location_id=location_id,
                                        item_id=item_id, status=status,
                                        page=page, page_size=page_size)


@app.get("/api/outcomes")
def list_outcomes_ep(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                     end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                     location_id: str | None = Query(None),
                     source: str | None = Query(None),
                     page: int = Query(1, ge=1),
                     page_size: int = Query(200, ge=1, le=1000),
                     x_api_key: str | None = Header(default=None)):
    """Recorded actual outcomes, newest service_date first."""
    _guard(x_api_key)
    return service.list_outcomes(start=start, end=end,
                                 location_id=location_id, source=source,
                                 page=page, page_size=page_size)


@app.get("/api/supply-plans")
def list_supply_plans_ep(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                         end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                         location_id: str | None = Query(None),
                         page: int = Query(1, ge=1),
                         page_size: int = Query(200, ge=1, le=1000),
                         x_api_key: str | None = Header(default=None)):
    """Confirmed supply plans, newest service_date first."""
    _guard(x_api_key)
    return service.list_supply_plans(start=start, end=end,
                                     location_id=location_id,
                                     page=page, page_size=page_size)


@app.get("/api/data/records")
def data_records_ep(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                    location_id: str | None = Query(None),
                    item_id: str | None = Query(None),
                    category: str | None = Query(None),
                    meal_period: str | None = Query(None),
                    search: str | None = Query(None),
                    page: int = Query(1, ge=1),
                    page_size: int = Query(200, ge=1, le=1000),
                    x_api_key: str | None = Header(default=None)):
    """Row-level explorer over the validated clean dataset."""
    _guard(x_api_key)
    return service.data_records(start=start, end=end,
                                location_id=location_id, item_id=item_id,
                                category=category, meal_period=meal_period,
                                search=search, page=page, page_size=page_size)


# --- Metrics / analytics / config ---------------------------------------------

@app.get("/api/metrics")
def metrics(x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    artifact = service.load_artifact()
    conn = db.connect(DB_PATH)
    try:
        return {
            "model": {
                "version": artifact.get("model_version") if artifact else None,
                "metrics_test": artifact.get("metrics_test") if artifact else None,
                "baselines_beaten": artifact.get("baselines_beaten") if artifact else None,
                "selected_strategy": artifact.get("selected_strategy") if artifact else None,
            },
            "feedback": db.feedback_metrics(conn),
        }
    finally:
        conn.close()


@app.get("/api/analytics")
def analytics(days: int = Query(28, ge=7, le=365),
              location_id: str | None = Query(None),
              category: str | None = Query(None),
              meal_period: str | None = Query(None),
              x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    try:
        return service.analytics_summary(days, location_id=location_id,
                                         category=category,
                                         meal_period=meal_period)
    except Exception as exc:
        raise _http_error(exc, "analytics_failed", 500)


# --- Dashboard insights & AI assistant -------------------------------------------

@app.get("/api/dashboard/overview")
def dashboard_overview(days: int | None = Query(None, ge=14, le=730),
                       location_id: str | None = Query(None),
                       category: str | None = Query(None),
                       meal_period: str | None = Query(None),
                       x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    try:
        return {
            "overview": insights.overview(days, location_id=location_id,
                                          category=category,
                                          meal_period=meal_period),
            "campus_map": insights.campus_map(),
            "bengaluru_map": insights.bengaluru_demand_map(),
            "india_context": insights.india_context_charts(),
        }
    except Exception as exc:
        raise _http_error(exc, "overview_failed", 500)


@app.get("/api/chat/sections")
def chat_sections(x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    return {"sections": chat.sections(),
            "llm_enabled": chat.groq_status()}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list)


@app.post("/api/chat")
def chat_ask(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    try:
        return chat.ask(req.message, req.history)
    except ValueError as exc:
        raise _http_error(exc, "invalid_message")
    except Exception as exc:
        raise _http_error(exc, "chat_failed", 500)


@app.get("/api/config/thresholds")
def get_thresholds_ep(x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    return get_thresholds()


@app.put("/api/config/thresholds")
def put_thresholds(req: ThresholdUpdate,
                   x_api_key: str | None = Header(default=None)):
    _guard(x_api_key)
    from .config import DEFAULT_THRESHOLDS, THRESHOLDS_PATH
    allowed = set(DEFAULT_THRESHOLDS) | {"weights"}
    bad = set(req.thresholds) - allowed
    if bad:
        raise _http_error(ValueError(f"unknown threshold keys: {sorted(bad)}"),
                          "invalid_thresholds")
    import json
    THRESHOLDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged = {**get_thresholds(), **req.thresholds}
    THRESHOLDS_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return {"saved": True, "thresholds": merged}


# --- Frontend -------------------------------------------------------------------

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
