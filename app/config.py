"""Central configuration. Environment variables override defaults.

Secrets (if any are ever needed) must come from environment variables,
never from this file.
"""
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Env-overridable so tests/sandboxes never write into the real data directory.
DATA_DIR = Path(os.environ.get("FSDB_DATA_DIR", PROJECT_ROOT / "data"))
CONFIG_DIR = PROJECT_ROOT / "config"
RAW_DATA_CSV = DATA_DIR / "raw_service_records.csv"
CLEAN_DATA_CSV = DATA_DIR / "clean_service_records.csv"
DB_PATH = Path(os.environ.get("FSDB_PATH", DATA_DIR / "app.db"))
THRESHOLDS_PATH = CONFIG_DIR / "thresholds.json"
WEB_DIR = PROJECT_ROOT / "web"

DEFAULT_THRESHOLDS = {
    # Surplus classification bands, as fractions of predicted demand.
    # expected_surplus = planned_supply - predicted_demand
    "shortage_ratio": -0.10,      # surplus <= -10% of demand  -> shortage
    "balanced_max_ratio": 0.05,   # (-10%, +5%]               -> balanced
    "low_surplus_max_ratio": 0.20,# (+5%, +20%]               -> low surplus
                                   # > +20%                    -> high surplus
    # Recommendation score weights (sum to 1.0). All factors normalised 0..1.
    "weights": {
        "need": 0.35,             # how much the destination is short / under-supplied
        "quantity_fit": 0.25,     # usable fraction of the source surplus
        "urgency": 0.20,          # time left in destination service window
        "proximity": 0.10,        # 1 = same location family, decays with distance
        "compatibility": 0.10,    # category match between source and destination
    },
    # A recommendation needs at least this transferable quantity to be worth proposing.
    "min_transfer_units": 5,
    # Distances in km between locations (reference data for logistics factor).
    "max_distance_km": 5.0,
}


def get_thresholds() -> dict:
    """Load operational thresholds from config/thresholds.json, falling back
    to defaults. Operators may edit that file without touching code."""
    if THRESHOLDS_PATH.exists():
        try:
            with open(THRESHOLDS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = json.loads(json.dumps(DEFAULT_THRESHOLDS))  # deep copy
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return json.loads(json.dumps(DEFAULT_THRESHOLDS))


# --- General service settings -------------------------------------------------
DATA_SEED = int(os.environ.get("FSDB_DATA_SEED", "42"))
DATA_DAYS = int(os.environ.get("FSDB_DATA_DAYS", "180"))
HOST = os.environ.get("FSDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("FSDB_PORT", "8000"))
LOG_LEVEL = os.environ.get("FSDB_LOG_LEVEL", "INFO")
