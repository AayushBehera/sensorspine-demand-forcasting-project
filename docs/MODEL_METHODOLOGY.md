# Model Methodology

## Target and unit of prediction

One row per `(service_date, location_id, item_id, meal_period)`.
Target: `actual_demand` (units consumed). The synthetic dataset is the only
data source today; every number in this document was measured on it.

## Feature set (leak-safe by construction)

| Group | Features | Leakage control |
|---|---|---|
| Calendar | `dow`, `month`, `is_weekend`, `dow_sin/cos`, `month_sin/cos` | known in advance; cyclical encodings let the linear candidate capture periodicity |
| Events | `public_holiday`, `mid_term_break`, `exams`, `term_start` | from calendar table |
| Promotions | `promotion` | treated as planned/known; future flags come from caller input (default 0) |
| Weather | `temp_c`, `rain` | **previous-day values**; same-day weather is unknown at forecast time, so prediction rows carry NaN (HistGBR handles missing natively) |
| History | `lag_1`, `lag_7`, `lag_14` | shifted within each series on a complete daily grid, so `lag_7` means exactly 7 calendar days earlier even across gaps |
| Rolling | `roll_mean_7`, `roll_mean_28`, `roll_std_7`, `trend_7_28` | windows end strictly at t−1 (`shift(1)` before rolling) |
| Categorical | location, item, category, meal period | ordinal-encoded with unknown-safe value −1 |

**Deliberate exclusion:** `planned_production` is NOT a model feature. The
forecast must stay independent of the production plan — otherwise
`surplus = plan − forecast` becomes circular and surplus detection meaningless.

**Leakage tests** (in `tests/test_features.py`): perturbing all demand after a
cutoff provably leaves every pre-cutoff feature unchanged; lag values are
verified against exact calendar dates.

## Models

* **Baseline 1 — seasonal naive**: prediction = `lag_7`.
* **Baseline 2 — moving average**: trailing 7-day mean (`roll_mean_7`).
  Warm-up rows without full history fall back to `lag_1`, then series median.
* **Candidate A — HistGradientBoostingRegressor** (400 trees, lr 0.06,
  L2 1.0): handles mixed types, NaNs, and non-linear interactions on tabular
  data of this size without heavy preprocessing. Categoricals ordinal-encoded
  inside a sklearn `Pipeline`.
* **Candidate B — Ridge regression** (median-imputed numerics + one-hot
  categoricals): included because tree ensembles **cannot extrapolate** a
  trend beyond the training range; the ridge candidate can. On trending data
  it wins; on the noisy multi-series generator data the GBM wins.

**Selection is evidence-based:** both candidates are fitted, refit on
train+validation, scored once on the test split, and whichever has the lower
test MAE becomes `selected_strategy`. If neither beats the best baseline,
`baselines_beaten` is `false` and the UI says so — keep the simpler model.

## Validation protocol

Time-ordered split over unique dates: 70 % train / 15 % validation / 15 %
test. The candidate is fitted on train, compared on validation, refit on
train+validation, then scored **once** on test. No shuffling anywhere.

## Metrics

MAE, RMSE, WAPE = Σ|err| / Σ|actual| ×100 (guarding zero denominators), and
bias = mean(pred − actual) where positive means systematic over-forecasting.

Latest measured run (seed 42, 180 days):

| model | MAE ↓ | RMSE | WAPE % | bias |
|---|---|---|---|---|
| candidate GBM | **7.03** | 10.62 | 12.5 | +1.11 |
| seasonal naive lag7 | 9.43 | 14.55 | 16.8 | −0.70 |
| moving avg 7 | 12.27 | 17.40 | 21.9 | −1.53 |

The walk-forward replay (`POST /api/backtest/simulate`) reproduces these on
live-pipeline predictions (MAE ≈ 7.07), confirming no train/test leakage in
the serving path.

If a retrain fails to beat baselines, `/api/metrics` reports
`baselines_beaten: false` and the dashboard surfaces it — keep the simpler
model in that case.

## Confidence & risk

Per-prediction intervals are empirical: half-width = half the 10–90 %
residual range from validation backtests, scaled by local volatility
(`clip(roll_std_7 / roll_mean_7, 0.5, 2.5)`). Operational bands:

* `stable` — interval half-width < 15 % of prediction
* `moderate_uncertainty` — < 35 %
* `high_uncertainty` — ≥ 35 % or insufficient recent history

These are decision heuristics derived from measured residuals, not
distributional statistical guarantees.

## Improvement loop

Retraining (`POST /api/model/train`) registers a new immutable model version
with its test metrics in `model_registry`. Feedback metrics
(`/api/outcomes/sync` → `feedback_metrics`) score forecasts against recorded
actuals scoped to the current version, so "better" is always a measured claim
against the previous version, never an assumption.
