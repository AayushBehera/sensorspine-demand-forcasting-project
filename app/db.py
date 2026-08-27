"""Persistence layer (stdlib sqlite3 - zero extra dependencies).

Entities: locations, items, forecasts, surplus_assessments,
recommendations, outcomes, model_registry. Auditability: every forecast,
assessment and recommendation stores its model version and timestamp;
outcomes record when/where actuals came from.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT
);
CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_date TEXT NOT NULL,
    location_id TEXT NOT NULL REFERENCES locations(location_id),
    item_id TEXT NOT NULL REFERENCES items(item_id),
    meal_period TEXT NOT NULL,
    predicted_demand REAL NOT NULL,
    interval_low REAL,
    interval_high REAL,
    stability_band TEXT,
    model_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(service_date, location_id, item_id, meal_period, model_version)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_date ON forecasts(service_date);
CREATE TABLE IF NOT EXISTS surplus_assessments (
    assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_date TEXT NOT NULL,
    location_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    meal_period TEXT NOT NULL,
    predicted_demand REAL,
    supply REAL,
    supply_basis TEXT,
    expected_surplus REAL,
    status TEXT,
    model_version TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assess_date ON surplus_assessments(service_date);
CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_date TEXT NOT NULL,
    source_location TEXT NOT NULL,
    source_item TEXT NOT NULL,
    available_surplus REAL,
    destination_location TEXT NOT NULL,
    predicted_need REAL,
    transfer_quantity REAL NOT NULL,
    score REAL NOT NULL,
    urgency TEXT,
    reason TEXT,
    factors_json TEXT,
    distance_km REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_at TEXT,
    outcome_units_moved REAL,
    outcome_note TEXT,
    model_version TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recs_date_status ON recommendations(service_date, status);
CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_date TEXT NOT NULL,
    location_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    meal_period TEXT NOT NULL,
    actual_demand REAL NOT NULL,
    actual_planned_production REAL,
    source TEXT NOT NULL DEFAULT 'dataset_sync',
    recorded_at TEXT NOT NULL,
    UNIQUE(service_date, location_id, item_id, meal_period)
);
CREATE INDEX IF NOT EXISTS idx_outcomes_date ON outcomes(service_date);
CREATE TABLE IF NOT EXISTS model_registry (
    model_version TEXT PRIMARY KEY,
    trained_at TEXT NOT NULL,
    data_end_date TEXT,
    selected_strategy TEXT,
    metrics_json TEXT
);
CREATE TABLE IF NOT EXISTS supply_plans (
    service_date TEXT NOT NULL,
    location_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    meal_period TEXT NOT NULL,
    supply REAL NOT NULL,
    posted_at TEXT NOT NULL,
    PRIMARY KEY (service_date, location_id, item_id, meal_period)
);
"""


_schema_ready = False


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    global _schema_ready
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not _schema_ready:
        conn.executescript(SCHEMA)
        _schema_ready = True
    return conn


def init_db(db_path: Path | None = None) -> None:
    global _schema_ready
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
    _schema_ready = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Reference data -----------------------------------------------------------

def upsert_reference(conn: sqlite3.Connection, locations: list[dict],
                     items: list[dict]) -> None:
    for loc in locations:
        conn.execute(
            "INSERT INTO locations(location_id,name,description) VALUES(?,?,?) "
            "ON CONFLICT(location_id) DO UPDATE SET name=excluded.name,"
            "description=excluded.description",
            (loc["location_id"], loc["name"], loc.get("description")))
    for it in items:
        conn.execute(
            "INSERT INTO items(item_id,name,category) VALUES(?,?,?) "
            "ON CONFLICT(item_id) DO UPDATE SET name=excluded.name,"
            "category=excluded.category",
            (it["item_id"], it["name"], it["category"]))


def get_reference(conn: sqlite3.Connection) -> dict:
    return {
        "locations": [dict(r) for r in conn.execute("SELECT * FROM locations")],
        "items": [dict(r) for r in conn.execute("SELECT * FROM items")],
    }


# --- Forecasts / assessments --------------------------------------------------

def save_forecasts(conn: sqlite3.Connection, frame, model_version: str) -> int:
    now = _now()
    rows = [
        (str(r["date"].date() if hasattr(r["date"], "date") else r["date"]),
         r["location_id"], r["item_id"], r["meal_period"],
         float(r["predicted_demand"]), float(r["interval_low"]),
         float(r["interval_high"]), r["stability_band"], model_version, now)
        for _, r in frame.iterrows()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO forecasts(service_date,location_id,item_id,"
        "meal_period,predicted_demand,interval_low,interval_high,stability_band,"
        "model_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def save_assessments(conn: sqlite3.Connection, frame, model_version: str) -> int:
    now = _now()
    rows = []
    for _, r in frame.iterrows():
        d = r.get("date")
        rows.append((
            str(d.date() if hasattr(d, "date") else d),
            r["location_id"], r["item_id"], r["meal_period"],
            None if pd_isna(r.get("predicted_demand")) else float(r["predicted_demand"]),
            None if pd_isna(r.get("supply")) else float(r["supply"]),
            r.get("supply_basis"),
            None if pd_isna(r.get("surplus")) else float(r["surplus"]),
            r.get("status"), model_version, now))
    conn.executemany(
        "INSERT INTO surplus_assessments(service_date,location_id,item_id,"
        "meal_period,predicted_demand,supply,supply_basis,expected_surplus,"
        "status,model_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def pd_isna(v) -> bool:
    try:
        import math
        return v is None or (isinstance(v, float) and math.isnan(v))
    except TypeError:
        return False


def save_recommendations(conn: sqlite3.Connection, recs: list[dict],
                         model_version: str) -> list[int]:
    now = _now()
    ids = []
    for r in recs:
        cur = conn.execute(
            "INSERT INTO recommendations(service_date,source_location,source_item,"
            "available_surplus,destination_location,predicted_need,transfer_quantity,"
            "score,urgency,reason,factors_json,distance_km,status,model_version,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'pending', ?, ?)",
            (r.get("date"), r["source_location"], r["source_item"],
             r.get("available_surplus"), r["destination_location"],
             r.get("predicted_need"), r["transfer_quantity"], r["score"],
             r.get("urgency"), r.get("reason"), json.dumps(r.get("factors", {})),
             r.get("distance_km"), model_version, now))
        ids.append(cur.lastrowid)
    return ids


def decide_recommendation(conn: sqlite3.Connection, rec_id: int, action: str,
                          units_moved: float | None = None,
                          note: str | None = None) -> bool:
    if action not in {"accepted", "rejected"}:
        raise ValueError("action must be 'accepted' or 'rejected'")
    cur = conn.execute(
        "UPDATE recommendations SET status=?, decided_at=?, outcome_units_moved=?,"
        "outcome_note=? WHERE recommendation_id=? AND status='pending'",
        (action, _now(), units_moved, note, rec_id))
    return cur.rowcount > 0


# --- Outcomes -----------------------------------------------------------------

def sync_outcomes(conn: sqlite3.Connection, clean_df) -> dict:
    """Load actuals from the dataset into `outcomes`; report how many past
    forecasts now have a matching actual."""
    now = _now()
    rows = [
        (str(r["date"].date() if hasattr(r["date"], "date") else r["date"]),
         r["location_id"], r["item_id"], r["meal_period"],
         float(r["actual_demand"]), float(r["planned_production"]), "dataset_sync", now)
        for _, r in clean_df.iterrows()
    ]
    before = conn.execute("SELECT COUNT(*) c FROM outcomes").fetchone()["c"]
    conn.executemany(
        "INSERT OR REPLACE INTO outcomes(service_date,location_id,item_id,"
        "meal_period,actual_demand,actual_planned_production,source,recorded_at) "
        "VALUES(?,?,?,?,?,?,?,?)", rows)
    matched = conn.execute(
        """SELECT COUNT(*) c FROM outcomes o JOIN forecasts f
           ON o.service_date=f.service_date AND o.location_id=f.location_id
           AND o.item_id=f.item_id AND o.meal_period=f.meal_period""").fetchone()["c"]
    return {"outcome_rows_total": conn.execute(
        "SELECT COUNT(*) c FROM outcomes").fetchone()["c"],
        "inserted_now": max(0, conn.total_changes),
        "rows_before": before,
        "forecasts_with_actuals": matched}


def feedback_metrics(conn: sqlite3.Connection, model_version: str | None = None) -> dict:
    """Forecast accuracy vs recorded actuals + recommendation acceptance.
    When model_version is given, only that version's forecasts are scored."""
    scope_sql, params = ("", [])
    if model_version:
        scope_sql = " WHERE f.model_version=?"
        params.append(model_version)
    rows = conn.execute(
        f"""SELECT f.predicted_demand p, o.actual_demand a
           FROM forecasts f JOIN outcomes o
           ON f.service_date=o.service_date AND f.location_id=o.location_id
           AND f.item_id=o.item_id AND f.meal_period=o.meal_period{scope_sql}""",
        params).fetchall()
    n = len(rows)
    if n:
        errs = [r["p"] - r["a"] for r in rows]
        mae = sum(abs(e) for e in errs) / n
        bias = sum(errs) / n
        denom = sum(abs(r["a"]) for r in rows) or 1.0
        wape = 100.0 * sum(abs(e) for e in errs) / denom
    else:
        mae = bias = wape = None

    rec_stats = conn.execute(
        """SELECT status, COUNT(*) c FROM recommendations GROUP BY status"""
    ).fetchall()
    by_status = {r["status"]: r["c"] for r in rec_stats}
    decided = sum(by_status.get(s, 0) for s in ("accepted", "rejected"))
    moved = conn.execute(
        "SELECT SUM(outcome_units_moved) s FROM recommendations WHERE "
        "status='accepted'").fetchone()["s"]

    # Avoidable-overproduction proxy: accepted transfers reduce surplus that
    # would otherwise be wasted IF the operator reports units actually moved.
    return {
        "forecasts_evaluated": n,
        "forecast_mae": round(mae, 2) if mae is not None else None,
        "forecast_bias": round(bias, 2) if bias is not None else None,
        "forecast_wape_pct": round(wape, 2) if wape is not None else None,
        "recommendations_by_status": by_status,
        "acceptance_rate_pct": round(
            100.0 * by_status.get("accepted", 0) / decided, 1) if decided else None,
        "units_redistributed_reported": moved or 0.0,
    }


def register_model(conn: sqlite3.Connection, model_version: str, trained_at: str,
                   data_end_date: str, selected_strategy: str,
                   metrics_test: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO model_registry VALUES(?,?,?,?,?)",
        (model_version, trained_at, data_end_date, selected_strategy,
         json.dumps(metrics_test)))


# --- Confirmed supply plans ---------------------------------------------------

def post_supply_plans(conn: sqlite3.Connection, plans: list[dict]) -> int:
    now = _now()
    rows = [(str(p["service_date"]), p["location_id"], p["item_id"],
             p["meal_period"], float(p["supply"]), now) for p in plans]
    conn.executemany(
        "INSERT OR REPLACE INTO supply_plans VALUES(?,?,?,?,?,?)", rows)
    return len(rows)


def get_supply_plans(conn: sqlite3.Connection, service_date: str):
    """Confirmed plans for a date as a DataFrame (empty if none posted)."""
    import pandas as pd
    rows = conn.execute(
        "SELECT service_date AS date, location_id, item_id, meal_period, supply,"
        " 'confirmed' AS supply_basis FROM supply_plans WHERE service_date=?",
        (service_date,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def latest_model_version(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT model_version FROM model_registry ORDER BY trained_at DESC LIMIT 1"
    ).fetchone()
    return row["model_version"] if row else None
