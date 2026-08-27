# Superseded artifacts — archived 2026-08-24

Nothing here was deleted from the project; these are the previous versions of
mutable working files, preserved before the 2026-08-24 data-completion pass.

| File | Why superseded |
|---|---|
| `app.db` | Held only ~70 days of operational history (README spec: 180 days). Rebuilt at full window, seed 42. |
| `model.joblib` | Trained on the short window. Retrained after rebuild. |
| `raw_service_records.csv` | Stale partial export (45 days, 2026-07-09..08-22) inconsistent with clean CSV (70 days). |
| `clean_service_records.csv` | 70-day export; replaced by full-window export. |
| `weather.csv` / `context_events.csv` | 45-day slices matching the stale raw export; replaced by full-window context. |

All files remain byte-identical to their pre-refactor state. Provenance of the
replacements is recorded in `data/provenance/` and `docs/data-sources.md`.
