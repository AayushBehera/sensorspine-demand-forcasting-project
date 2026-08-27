# Sensorspine — Food-Service Demand Forecasting & Surplus Redistribution

A decision-support platform for campus and hospitality food service:
**demand forecast → confidence → surplus/shortage detection → ranked,
explainable redistribution recommendations → outcome feedback → evaluation.**

> **Data label:** operational transactions are **synthetic**, generator-versioned
> (`app/data_generator.py`, seed-controlled, every row `is_synthetic=true`)
> until live POS/transaction feeds are connected. The **context layer is
> production-real**: official HCES 2023-24 Bengaluru consumption microdata,
> real ERA5 weather for Bengaluru, and the real Indian public-holiday
> calendar — see [docs/data-sources.md](docs/data-sources.md) for full provenance.

---

## Production setup

```bash
pip install -r requirements.txt

python scripts/run_pipeline.py            # provision: data -> validate -> train -> run -> backtest
python scripts/run_pipeline.py --skip-backtest   # provisioning only
```

Run the API server:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000   # then open http://<host>:8000
```

### Deployment checklist

| Concern | Setting |
|---|---|
| **Auth** | Set `FSDB_API_KEY` before exposing beyond localhost; all `/api/*` calls then require header `X-API-Key`. |
| **Persistence** | SQLite at `FSDB_PATH`; back up that file plus `data/model.joblib` (registered model versions live in the DB). |
| **Capacity** | Scale with `uvicorn --workers N`; each worker needs its own `FSDB_PATH` or an external SQLite-safe strategy. |
| **Logging** | `FSDB_LOG_LEVEL` (`INFO` default); structured JSON errors on every API failure. |
| **Reproducibility** | Rebuilds are deterministic per seed: `--seed` / `FSDB_DATA_SEED`, window via `--days` / `FSDB_DATA_DAYS`. |
| **Ops endpoints** | `GET /api/health` for readiness, `GET /api/metrics` + `GET /api/analytics` for monitoring. |
| **Thresholds** | Operational thresholds editable live via `PUT /api/config/thresholds`. |

The dashboard guides a fresh environment through its own setup (generate →
validate → train), so `scripts/run_pipeline.py` is optional but faster.
`scripts/run_demo.py` remains as a compatibility alias.

Run tests:

```bash
pytest -q
```

## What it does

| Stage | Module | Notes |
|---|---|---|
| Synthetic data | `app/data_generator.py` | 5 locations × 6 items × meal periods, 180 days; weekday/term/holiday/promo/weather effects; EWMA-style kitchen planning creates organic surpluses |
| Validation & cleaning | `app/validation.py` | schema checks, bad dates/duplicates/negatives dropped, outliers winsorised, raw vs clean CSVs separated, structured report + health check |
| Feature engineering | `app/features.py` | leak-safe lags (1/7/14), shifted rolling stats, calendar/event flags, previous-day weather; **planned production deliberately excluded from model features** |
| Forecasting | `app/forecasting.py` | seasonal-naive & 7-day-moving-average baselines vs two candidates (gradient boosting + trend-capable ridge); **selection by test MAE**; time-ordered split; MAE/RMSE/WAPE/bias; empirical ~80% intervals + stability bands |
| Surplus engine | `app/surplus.py` | expected surplus = supply − forecast; configurable bands (shortage/balanced/low/high); supply labelled *confirmed* vs *estimated* |
| Redistribution | `app/recommend.py` | transparent weighted scoring (need / quantity-fit / urgency / proximity / compatibility), greedy allocation caps, human-readable reasons |
| Feedback loop | `app/db.py`, `/api/outcomes/*` | actuals recorded; forecast-vs-actual error, acceptance rate, units redistributed reported |
| Walk-forward backtest | `/api/backtest/simulate` | replays recent days using only prior history → honest out-of-sample evaluation |

Measured on the synthetic test window (seed 42, full 180-day dataset,
2026-08-24 rebuild): the gradient-boosting candidate wins selection with
**MAE ≈ 6.5 units, WAPE ≈ 12.9%**, beating seasonal-naive and moving-average;
walk-forward live check over the final 14 days gives MAE ≈ 8.4. Numbers
regenerate with the data; never quote them without rerunning.

## Architecture

```
web/            static dashboard (vanilla JS + SVG charts, no build step)
app/
  main.py       FastAPI routes (thin; validation + errors only)
  service.py    orchestration of the full loop
  config.py     env-overridable settings; thresholds in config/thresholds.json
  db.py         sqlite3 schema + persistence (stdlib, no ORM)
  india_context.py  REAL India context bridge (weather/holidays/HCES shares)
  data_generator.py validation.py features.py forecasting.py surplus.py recommend.py
data_pipeline/  acquire -> context_fetch -> normalize -> scenarios -> ablation
data/
  raw/{official,research,community}/   preserved downloads (sha256 recorded)
  processed/{consumption,restaurant,waste,weather,metadata,context}/
  synthetic/operational/               labelled scenario frames
  provenance/                          dataset metadata + quality reports
scripts/run_pipeline.py one-command pipeline bootstrap
tests/          unit / ML / surplus / recommendation / API / integration / data-integration
```

### India data layer (new)

| Layer | Source | Provenance |
|---|---|---|
| Consumption composition | HCES 2023-24 Bengaluru unit-level microdata (MoSPI via OpenCity mirror) + official HCES factsheet MPCE trends (2011-12→2023-24) | OFFICIAL |
| Consumption microdata (2nd state) | HCES 2022-23 Level-4, 2,516 urban Maharashtra households (data.gov.in export; layout flagged) | OFFICIAL |
| Price context | RS-251 monthly food inflation 2014-2020 | OFFICIAL |
| Supply references | Market arrivals by district-year; national crop production; buffer stocks; processing capacity by state | OFFICIAL |
| Restaurant/menu metadata | Swiggy listings, 534 Indian cities + Bengaluru online-food order survey | COMMUNITY |
| Food/nutrition reference | IFCT 2017 (ICMR-NIN) | RESEARCH |
| Waste benchmark | UNEP Food Waste Index sector table — India food service **28 kg/capita/yr** | RESEARCH (UNEP) |
| Weather features | Open-Meteo ERA5, Bengaluru daily | OFFICIAL-open |
| Holiday/festival flags | `holidays` package India calendars | DERIVED |

Docs: [data-sources](docs/data-sources.md) ·
[dataset-compatibility](docs/dataset-compatibility.md) ·
[data-dictionary](docs/data-dictionary.md) ·
[data-pipeline](docs/data-pipeline.md) ·
[synthetic-data](docs/synthetic-data.md) ·
[model-data-lineage](docs/model-data-lineage.md).

### Key API endpoints

| Method & path | Purpose |
|---|---|
| `GET  /api/health` | DB/data/model readiness |
| `POST /api/data/generate?seed&days` | rebuild the synthetic dataset |
| `POST /api/data/validate` | validate + write cleaned CSV, return report |
| `POST /api/model/train` | baselines vs GBM, register version + metrics |
| `POST /api/day/run {date?, planned_promotions?}` | forecast → surplus → recommendations (persisted) |
| `GET  /api/recommendations?date&status&limit` | stored recommendations |
| `POST /api/recommendations/{id}/decision {action, units_moved?}` | accept/dismiss + record outcome |
| `POST /api/supply-plans` | operator-posted confirmed supply for a date |
| `POST /api/backtest/simulate?days` | walk-forward replay of past days |
| `POST /api/outcomes/sync` · `POST /api/outcomes/manual` | load/score actuals |
| `GET  /api/metrics` · `GET /api/analytics?days` | model + feedback + trend aggregates |
| `GET/PUT /api/config/thresholds` | read/edit operational thresholds |

Interactive docs: `http://127.0.0.1:8000/docs`.

## Configuration

Environment variables: `FSDB_PATH` (db file), `FSDB_DATA_SEED`,
`FSDB_DATA_DAYS`, `FSDB_HOST`, `FSDB_PORT`, `FSDB_LOG_LEVEL`,
`FSDB_API_KEY` (when set, all `/api/*` calls require header `X-API-Key`).

Operational thresholds live in `config/thresholds.json`
(surplus band ratios, recommendation weights, minimum transfer size) and can
be edited live via `PUT /api/config/thresholds`.

## Limitations & honesty labels

* **Synthetic**: dataset, locations and distances are generator-built
  placeholders until live transaction feeds are connected; every row is
  labelled `is_synthetic=true` with generator version + scenario.
* **Estimated supply**: unless operators post plans via `/api/supply-plans`,
  supply is estimated from recent planning behaviour and labelled as such.
* **Confidence intervals** are empirical (~80% of backtest residuals scaled by
  local volatility) — operational guidance, not statistical guarantees.
* **No automatic learning**: "improvement" means retraining via
  `/api/model/train` and comparing registered versions; nothing retrains itself.
* **No auth by default**: set `FSDB_API_KEY` before exposing beyond localhost.
* Transfers require staff confirmation; this tool does not handle food-safety
  logistics (temperature, allergens, holding times).

See `docs/MODEL_METHODOLOGY.md` and `docs/RECOMMENDATION_LOGIC.md` for the
full method descriptions.
# c--
