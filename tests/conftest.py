import os
import tempfile

# Must run before any app import: isolate the test database AND the data
# directory (generate()/run_validation() write CSVs into DATA_DIR; without
# this they would overwrite the real 180-day dataset on every test run).
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="fsdb_test_data_")
os.environ["FSDB_PATH"] = os.path.join(_TEST_DATA_DIR, "test.db")
os.environ["FSDB_DATA_DIR"] = _TEST_DATA_DIR

# Provenance metadata is small (~52 KB) and read-only; copy it so tests that
# exercise the dashboard's Data-tab snapshot see the same facts as production.
from pathlib import Path  # noqa: E402
import shutil  # noqa: E402

_REAL_PROVENANCE = Path(__file__).resolve().parent.parent / "data" / "provenance"
if _REAL_PROVENANCE.is_dir():
    shutil.copytree(_REAL_PROVENANCE, Path(_TEST_DATA_DIR) / "provenance")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _clean_db():
    path = os.environ["FSDB_PATH"]
    if os.path.exists(path):
        os.remove(path)
    yield
    import shutil

    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture()
def small_clean():
    """A small validated clean frame built from the generator (fast)."""
    import pandas as pd

    from app.data_generator import generate
    from app.validation import validate_and_clean

    frames = generate(days=45, seed=7)
    clean, report = validate_and_clean(
        frames["services"], frames["weather"], frames["context_events"])
    assert report["rows_out"] > 0
    clean["date"] = pd.to_datetime(clean["date"])
    return clean


def easy_clean(days: int = 220):
    """Deterministic, strongly-learnable series: weekly cycle + linear trend
    + tiny noise. Used to prove the candidate model beats baselines when the
    signal is real (baselines stay honest competitors on noisy short data)."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(11)
    dates = pd.date_range("2026-01-01", periods=days, freq="D")
    rows = []
    for loc in ("L1", "L2"):
        for i in range(days):
            d = dates[i]
            base = 50 if loc == "L1" else 30
            demand = (base
                      + 15 * np.sin(2 * np.pi * d.dayofweek / 7)
                      + 0.4 * i
                      + rng.normal(0, 1.5))
            rows.append({
                "date": d, "location_id": loc, "item_id": "I1",
                "category": "hot_meal", "meal_period": "lunch",
                "planned_production": demand + 5,
                "actual_demand": max(demand, 0.0),
                "promotion": int(i % 14 == 0),
                "temp_c": 15.0, "rain": 0,
                "public_holiday": 0, "mid_term_break": 0,
                "exams": 0, "term_start": 0,
            })
    return pd.DataFrame(rows)


@pytest.fixture()
def easy_data():
    return easy_clean()
