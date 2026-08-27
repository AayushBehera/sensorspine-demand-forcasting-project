"""Service layer: orchestrates the Forecast-to-Action loop.

    data -> validation -> features -> forecast -> confidence
         -> surplus/shortage -> recommendations -> persistence

Route handlers stay thin; all business logic lives here.
Model artifacts are persisted to disk so the API never retrains per request.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

import joblib
import pandas as pd

from . import db
from .config import (CLEAN_DATA_CSV, DATA_DIR, DB_PATH, RAW_DATA_CSV,
                     get_thresholds)
from .data_generator import ITEMS, LOCATIONS, generate
from .features import build_features, temporal_split
from .forecasting import forecast_future, train_and_evaluate
from .recommend import build_recommendations
from .surplus import assess, estimate_supply, summarize_day
from .validation import health_check, validate_and_clean

log = logging.getLogger("sensorspine.service")

MODEL_PATH = DATA_DIR / "model.joblib"


# --- Data ---------------------------------------------------------------------

def load_raw() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    services = pd.read_csv(RAW_DATA_CSV)
    weather = pd.read_csv(DATA_DIR / "weather.csv")
    context = pd.read_csv(DATA_DIR / "context_events.csv")
    return services, weather, context


def load_distances() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "distances.csv")


def last_context_provenance() -> dict:
    """How much of the current dataset's context is real vs synthetic."""
    import json
    p = DATA_DIR / "context_provenance.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"weather_real_rows": 0, "weather_synthetic_rows": 0,
            "note": "context provenance not recorded; regenerate data"}


def run_validation() -> dict:
    """Validate raw data; write cleaned CSV separately from raw."""
    if not RAW_DATA_CSV.exists():
        raise FileNotFoundError(
            f"raw dataset missing at {RAW_DATA_CSV}; generate it first "
            "(POST /api/data/generate or scripts/run_pipeline.py)")
    services, weather, context = load_raw()
    clean, report = validate_and_clean(services, weather, context)
    CLEAN_DATA_CSV.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(CLEAN_DATA_CSV, index=False)
    report["health"] = health_check(clean)
    return report


def get_clean() -> pd.DataFrame:
    if not CLEAN_DATA_CSV.exists():
        run_validation()
    df = pd.read_csv(CLEAN_DATA_CSV)
    df["date"] = pd.to_datetime(df["date"])
    return df


def regenerate_data(seed: int, days: int) -> dict:
    frames = generate(start=date_cls.today() - timedelta(days=days),
                      days=days, seed=seed)
    # Invalidate downstream artifacts: they describe the previous dataset.
    for p in (CLEAN_DATA_CSV, MODEL_PATH):
        Path(p).unlink(missing_ok=True)
    return {"rows": len(frames["services"]),
            "date_min": str(frames["services"]["date"].min()),
            "date_max": str(frames["services"]["date"].max()),
            "context_provenance": frames.get("context_provenance", {})}


# --- Model training -----------------------------------------------------------

def train_pipeline(seed: int = 42) -> dict:
    clean = get_clean()
    feat = build_features(clean)
    if len(feat) < 200:
        raise ValueError(f"not enough supervised rows ({len(feat)}) to train")
    train_df, val_df, test_df = temporal_split(feat)
    result = train_and_evaluate(train_df, val_df, test_df, seed=seed)

    version = "mdl-" + hashlib.sha1(
        f"{result['trained_at']}|{clean['date'].max()}|{len(clean)}".encode()
    ).hexdigest()[:10]

    artifact = {k: v for k, v in result.items()
                if k != "test_predictions_frame"}
    artifact["model_version"] = version
    artifact["data_end_date"] = str(clean["date"].max().date())
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, MODEL_PATH)

    conn = db.connect(DB_PATH)
    try:
        db.upsert_reference(conn, LOCATIONS_REF, ITEMS_REF)
        db.register_model(conn, version, result["trained_at"],
                          artifact["data_end_date"], result["selected_strategy"],
                          result["metrics_test"])
        conn.commit()
    finally:
        conn.close()

    summary = {
        "model_version": version,
        "selected_strategy": result["selected_strategy"],
        "baselines_beaten": result["baselines_beaten"],
        "metrics_test": result["metrics_test"],
        "metrics_validation": result["metrics_validation"],
        "train_rows": len(train_df), "val_rows": len(val_df),
        "test_rows": len(test_df),
        "data_end_date": artifact["data_end_date"],
    }
    log.info("trained model %s: test MAE %.2f", version,
             result["metrics_test"]["candidate_gbm"]["mae"])
    return summary


LOCATIONS_REF = [{"location_id": lid, "name": name, "description": role}
                 for lid, name, _s, _p, role in LOCATIONS]
ITEMS_REF = [{"item_id": iid, "name": nm, "category": cat}
             for iid, nm, cat, _pop in ITEMS]


def load_artifact() -> dict | None:
    if not MODEL_PATH.exists():
        return None
    return joblib.load(MODEL_PATH)


# --- Forecast-to-Action day run -------------------------------------------------

def next_service_dates(n: int = 1) -> list[str]:
    clean = get_clean()
    last = clean["date"].max().normalize()
    d0 = max(last + timedelta(days=1), pd.Timestamp.today().normalize())
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def run_day(target_dates: list[str],
            planned_promotions: dict[str, int] | None = None,
            persist: bool = True) -> dict:
    """One full Forecast-to-Action pass for the given service date(s)."""
    artifact = load_artifact()
    if artifact is None:
        raise RuntimeError("no trained model available; call /api/model/train first")
    clean = get_clean()

    forecasts = forecast_future(clean, target_dates, artifact,
                                planned_promotions=planned_promotions)

    thresholds = get_thresholds()
    conn = db.connect(DB_PATH)
    try:
        supplies = [estimate_supply(clean)]
        for td in target_dates:
            plans = db.get_supply_plans(conn, td)
            if len(plans):
                supplies.append(plans)
        supply = pd.concat(supplies, ignore_index=True).drop_duplicates(
            subset=["location_id", "item_id", "meal_period"], keep="first")

        assessment = assess(forecasts, supply, thresholds)
        recs = build_recommendations(assessment, load_distances(),
                                     thresholds)

        payload = {
            "target_dates": target_dates,
            "model_version": artifact.get("model_version", "unknown"),
            "forecasts": frame_to_records(forecasts),
            "assessment_summary": summarize_day(assessment),
            "assessments": frame_to_records(assessment),
            "recommendations": recs,
        }

        if persist:
            n_f = db.save_forecasts(conn, forecasts, artifact["model_version"])
            n_a = db.save_assessments(conn, assessment, artifact["model_version"])
            ids = db.save_recommendations(conn, recs, artifact["model_version"])
            conn.commit()
            payload["stored"] = {"forecasts": n_f, "assessments": n_a,
                                 "recommendations": len(ids)}
    finally:
        conn.close()
    return payload


def frame_to_records(frame: pd.DataFrame) -> list[dict]:
    out = frame.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records"))


# --- Walk-forward backtest (honest forecast-vs-actual evaluation) ---------------

def simulate_backtest(days: int = 14) -> dict:
    """Replay the last `days` service days one at a time.

    For each day T the feature builder sees ONLY rows before T, and the model
    was trained strictly before the test window (temporal split), so these
    are genuine out-of-sample predictions. Results land in `forecasts` and
    join recorded actuals via /api/outcomes/sync.
    """
    artifact = load_artifact()
    if artifact is None:
        raise RuntimeError("no trained model available; call /api/model/train first")
    clean = get_clean()

    all_days = sorted(clean["date"].unique())
    if len(all_days) < days + 30:
        raise ValueError("not enough history to simulate")
    targets = [str(pd.Timestamp(d).date()) for d in all_days[-days:]]

    conn = db.connect(DB_PATH)
    try:
        total = 0
        for td in targets:
            hist = clean[clean["date"] < pd.Timestamp(td)]
            fc = forecast_future(hist, [td], artifact)
            sup = estimate_supply(hist)
            a = assess(fc, sup)
            total += db.save_forecasts(conn, fc, artifact["model_version"])
            db.save_assessments(conn, a, artifact["model_version"])
        # Load actuals so the simulated forecasts can be scored immediately.
        db.sync_outcomes(conn, clean)
        conn.commit()
        feedback = db.feedback_metrics(conn, model_version=artifact["model_version"])
        return {"simulated_dates": targets, "forecast_rows": total,
                "feedback_metrics": feedback}
    finally:
        conn.close()


# --- Feedback -------------------------------------------------------------------

def sync_outcomes() -> dict:
    clean = get_clean()
    conn = db.connect(DB_PATH)
    try:
        stats = db.sync_outcomes(conn, clean)
        conn.commit()
        return stats
    finally:
        conn.close()


def record_manual_outcome(service_date: str, location_id: str, item_id: str,
                          meal_period: str, actual_demand: float) -> int:
    import sqlite3
    conn = db.connect(DB_PATH)
    try:
        cur = conn.execute(
            "INSERT OR REPLACE INTO outcomes(service_date,location_id,item_id,"
            "meal_period,actual_demand,actual_planned_production,source,recorded_at)"
            " VALUES(?,?,?,?,?,NULL,'manual',?)",
            (service_date, location_id, item_id, meal_period,
             float(actual_demand), db._now()))
        conn.commit()
        return cur.rowcount
    except sqlite3.Error as exc:
        raise RuntimeError(f"outcome not recorded: {exc}") from exc
    finally:
        conn.close()


def analytics_summary(days: int = 28, location_id: str | None = None,
                      category: str | None = None,
                      meal_period: str | None = None) -> dict:
    """Aggregates for the dashboard analytics tab."""
    clean = get_clean()
    cutoff = clean["date"].max() - pd.Timedelta(days=days)
    recent = clean[clean["date"] > cutoff]
    if location_id:
        recent = recent[recent["location_id"] == location_id]
    if category:
        recent = recent[recent["category"] == category]
    if meal_period:
        recent = recent[recent["meal_period"] == meal_period]

    by_day = (recent.groupby(recent["date"].dt.strftime("%Y-%m-%d"))
              ["actual_demand"].sum())
    by_dow = recent.groupby(recent["date"].dt.dayofweek)["actual_demand"].mean()
    by_loc = recent.groupby("location_id")["actual_demand"].sum().sort_values()
    waste = (recent.assign(w=(recent["planned_production"] - recent["actual_demand"])
                           .clip(lower=0))
             .groupby("location_id")["w"].sum().sort_values())

    conn = db.connect(DB_PATH)
    try:
        latest = db.latest_model_version(conn)
        feedback = db.feedback_metrics(conn, model_version=latest)
        registry = [dict(r) for r in conn.execute(
            "SELECT * FROM model_registry ORDER BY trained_at DESC LIMIT 5")]
        hist_sql = """SELECT f.service_date d, f.location_id l, f.item_id i,
                      f.meal_period mp, f.predicted_demand p, o.actual_demand a
                FROM forecasts f JOIN outcomes o ON
                f.service_date=o.service_date AND f.location_id=o.location_id
                AND f.item_id=o.item_id AND f.meal_period=o.meal_period
                JOIN items it ON it.item_id=f.item_id"""
        hwhere: list = []
        hparams: list = []
        if location_id:
            hwhere.append("f.location_id=?"); hparams.append(location_id)
        if category:
            hwhere.append("it.category=?"); hparams.append(category)
        if meal_period:
            hwhere.append("f.meal_period=?"); hparams.append(meal_period)
        if hwhere:
            hist_sql += " WHERE " + " AND ".join(hwhere)
        hist_sql += " ORDER BY f.service_date DESC LIMIT 500"
        hist = [dict(r) for r in conn.execute(hist_sql, hparams)]
    finally:
        conn.close()

    return {
        "window_days": days,
        "demand_by_day": {k: round(v, 1) for k, v in by_day.items()},
        "avg_demand_by_weekday": {int(k): round(v, 1) for k, v in by_dow.items()},
        "demand_share_by_location": {k: round(v, 1) for k, v in by_loc.items()},
        "wasted_units_by_location": {k: round(v, 1) for k, v in waste.items()},
        "feedback_metrics": feedback,
        "model_registry": registry,
        "forecast_vs_actual_sample": hist,
    }


# --- Paginated read models (additive GET endpoints) -------------------------------

def _eq(where: list, params: list, col: str, value) -> None:
    if value:
        where.append(f"{col} = ?"); params.append(value)


def _date_range(where: list, params: list, col: str, start, end) -> None:
    if start:
        where.append(f"{col} >= ?"); params.append(start)
    if end:
        where.append(f"{col} <= ?"); params.append(end)


def _paged(conn, table: str, where: list, params: list, order: str,
           page: int, page_size: int) -> dict:
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) c FROM {table} {clause}", params).fetchone()["c"]
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM {table} {clause} ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size])]
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def _list_table(table: str, where: list, params: list, page: int,
                page_size: int) -> dict:
    conn = db.connect(DB_PATH)
    try:
        return _paged(conn, table, where, params, "service_date DESC",
                      page, page_size)
    finally:
        conn.close()


def list_forecasts(start=None, end=None, location_id=None, item_id=None,
                   meal_period=None, model_version=None, page=1,
                   page_size=200) -> dict:
    where: list = []; params: list = []
    _date_range(where, params, "service_date", start, end)
    for col, v in (("location_id", location_id), ("item_id", item_id),
                   ("meal_period", meal_period),
                   ("model_version", model_version)):
        _eq(where, params, col, v)
    return _list_table("forecasts", where, params, page, page_size)


def list_surplus_history(start=None, end=None, location_id=None, item_id=None,
                         status=None, page=1, page_size=200) -> dict:
    where: list = []; params: list = []
    _date_range(where, params, "service_date", start, end)
    for col, v in (("location_id", location_id), ("item_id", item_id),
                   ("status", status)):
        _eq(where, params, col, v)
    return _list_table("surplus_assessments", where, params, page, page_size)


def list_outcomes(start=None, end=None, location_id=None, source=None,
                  page=1, page_size=200) -> dict:
    where: list = []; params: list = []
    _date_range(where, params, "service_date", start, end)
    for col, v in (("location_id", location_id), ("source", source)):
        _eq(where, params, col, v)
    return _list_table("outcomes", where, params, page, page_size)


def list_supply_plans(start=None, end=None, location_id=None,
                      page=1, page_size=200) -> dict:
    where: list = []; params: list = []
    _date_range(where, params, "service_date", start, end)
    _eq(where, params, "location_id", location_id)
    return _list_table("supply_plans", where, params, page, page_size)


def data_records(start=None, end=None, location_id=None, item_id=None,
                 category=None, meal_period=None, search=None, page=1,
                 page_size=200) -> dict:
    """Row-level explorer over the validated clean dataset."""
    df = get_clean()
    if start:
        df = df[df["date"].dt.strftime("%Y-%m-%d") >= start]
    if end:
        df = df[df["date"].dt.strftime("%Y-%m-%d") <= end]
    for col, v in (("location_id", location_id), ("item_id", item_id),
                   ("category", category), ("meal_period", meal_period)):
        if v:
            df = df[df[col] == v]
    if search:
        s = search.casefold()
        mask = False
        for c in ("location_id", "item_id", "category"):
            mask = mask | df[c].astype(str).str.casefold().str.contains(
                s, regex=False)
        df = df[mask]
    df = df.sort_values(["date", "location_id", "item_id", "meal_period"],
                        ascending=[False, True, True, True])
    total = int(len(df))
    lo = (page - 1) * page_size
    out = df.iloc[lo:lo + page_size].copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    items = json.loads(out.to_json(orient="records"))
    return {"items": items, "total": total, "page": page,
            "page_size": page_size, "count": total}


def list_recommendations(status: str | None = None, location_id: str | None = None,
                         limit: int = 500) -> list[dict]:
    """Redistribution recommendations (optionally filtered)."""
    conn = db.connect(DB_PATH)
    try:
        where: list = []
        params: list = []
        if status:
            where.append("status = ?"); params.append(status)
        if location_id:
            where.append("(source_location = ? OR destination_location = ?)")
            params.extend([location_id, location_id])
        sql = "SELECT * FROM recommendations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY service_date DESC, score DESC LIMIT ?"
        params.append(int(limit))
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()
