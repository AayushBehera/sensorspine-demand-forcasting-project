# Model & Data Lineage

Where every number the system shows actually comes from.

```
forecast_demand
  ← forecasting model (candidate GBM / ridge, versioned mdl-*)
  ← features: lags 1/7/14, rolling mean/std 7/28, calendar cyclical encodings
  ← context flags: public_holiday (REAL Indian calendar), exams/term/breaks (SYNTHETIC)
     promotion, temp_c/rain (REAL ERA5 Bengaluru, previous-day; leak-safe)
  ← clean_service_records.csv ← validation of raw_service_records.csv
     ← SYNTHETIC operational simulator v2.0-india-context

expected_surplus
  = supply − forecast_demand
  ← supply_plans (operator-confirmed) or EWMA estimate (labelled 'estimated')

recommendation score
  = 100 × Σ weights × {need, quantity_fit, urgency, proximity, compatibility}
  ← surplus assessment + distances.csv (SYNTHETIC reference)

feedback metrics (MAE/bias/WAPE, acceptance rate)
  ← outcomes table (actuals synced from dataset or recorded manually)
  ← joined to forecasts by (date, location, item, meal_period)

data provenance shown in dashboard Data tab
  ← data/provenance/dataset_metadata.json + quality_reports.json
  ← data_pipeline/acquire.py + normalize.py (sha256, download dates)
```

## Ablation record (measured 2026-08-22, seed 42, 180-day window)

Question: does REAL India context improve forecast accuracy?

| Model | test MAE real-context | test MAE synth-context | Δ |
|---|---|---|---|
| candidate_gbm | 6.83 | 6.84 | +0.01 |
| ridge_linear | 9.17 | 8.29 | −0.87 |
| seasonal_naive_lag7 | 8.87 | 9.06 | +0.19 |
| moving_avg_7 | 11.83 | 12.27 | +0.44 |

**Honest reading:** on this synthetic simulator the autoregressive signal
dominates; real weather/holidays are MAE-neutral for the selected GBM and
slightly *hurt* the linear model on this window. Real context is kept because
inputs are credible (real monsoon, real festivals) and the pipeline is ready
for real transaction data — NOT because it improves measured accuracy.
Reproduce with `python data_pipeline/ablation_context.py`.

## Canonical production run (same date)

GBM trained via `POST /api/model/train` after regeneration:
test **MAE 6.81**, WAPE 13.0%, beats seasonal-naive (9.32) and moving-average
(12.63); registered as `mdl-171aa524ae` with dataset end-date stamped.

## Known weakness (measured, not hidden)

Walk-forward replay of the FINAL 7 days (the simulated exam period, a demand
regime shift) scores **MAE 15.8 with bias +9.2** versus the global test MAE
6.81 — the model systematically over-forecasts during that regime. This is
exactly the kind of error the feedback loop exists to surface; candidates:
exam-specific features or regime detection when real calendars are available.

## Versioning rules

* Every training writes a new `model_registry` row (version hash includes
  timestamp + data fingerprint); evaluation results are never overwritten.
* Dataset regeneration invalidates `clean_service_records.csv` and
  `model.joblib` so stale artefacts can't be served.
