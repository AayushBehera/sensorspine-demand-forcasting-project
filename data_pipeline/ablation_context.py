"""Ablation: does REAL India context actually improve forecasting?

Runs the full pipeline twice with identical seed/code:
  A) real Bengaluru weather + real Indian holidays
  B) context files hidden -> generator falls back to synthetic
Prints test-split metrics for each candidate/baseline.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

from app import service
from app.config import CLEAN_DATA_CSV, DATA_DIR
from app.data_generator import generate
from app.features import build_features, temporal_split
from app.forecasting import train_and_evaluate

from app.india_context import load_india_holidays, load_weather_table

W = DATA_DIR / "processed" / "weather" / "bengaluru_era5_daily.csv"
H = DATA_DIR / "processed" / "context" / "india_public_holidays.csv"


def run_once(label: str) -> dict:
    frames = generate(start=date(2026, 2, 1), days=180, seed=42)
    services, weather, context = frames["services"], frames["weather"], frames["context_events"]
    from app.validation import validate_and_clean
    clean, _ = validate_and_clean(services, weather, context)
    feat = build_features(clean)
    tr, va, te = temporal_split(feat)
    res = train_and_evaluate(tr, va, te)
    print(f"--- {label} ---")
    for name, m in res["metrics_test"].items():
        print(f"  {name:22s} MAE {m['mae']:6.2f}  RMSE {m['rmse']:6.2f}  "
              f"WAPE {m['wape_pct']:5.1f}%  bias {m['bias']:+.2f}")
    return {k: v["mae"] for k, v in res["metrics_test"].items()}


real_mae = run_once("A) REAL India context")

load_weather_table.cache_clear()
load_india_holidays.cache_clear()
W.rename(W.with_suffix(".bak"))
H.rename(H.with_suffix(".bak"))
try:
    load_weather_table.cache_clear()
    load_india_holidays.cache_clear()
    synth_mae = run_once("B) SYNTHETIC fallback context")
finally:
    W.with_suffix(".bak").rename(W)
    H.with_suffix(".bak").rename(H)

print("\n=== ABLATION SUMMARY (test MAE, lower is better) ===")
for k in real_mae:
    delta = synth_mae[k] - real_mae[k]
    print(f"  {k:22s} real={real_mae[k]:6.2f}  synth={synth_mae[k]:6.2f}  "
          f"delta={delta:+.2f}")
