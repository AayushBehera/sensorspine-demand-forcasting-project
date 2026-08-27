# Redistribution Recommendation Logic

## Inputs

Per service date, the surplus engine produces one assessment row per series:

```
expected_surplus = supply − predicted_demand
status = shortage | balanced | low_surplus | high_surplus | unknown_supply
```

`supply` is either **confirmed** (operator posted via `POST /api/supply-plans`)
or **estimated** (median planned production of the last 14 days) — always
labelled in the payload and dashboard.

## Candidate generation

For every (source series with surplus > 0, destination series with
`predicted_demand − supply > 0`) pair where **item matches** and locations
differ, a transfer candidate is created. Quantity is capped by both the
source's remaining surplus and the destination's remaining need (greedy,
highest score first). Candidates below `min_transfer_units` are dropped.

## Scoring — fully transparent

All five factors are normalised to 0..1 and combined with weights from
`config/thresholds.json` (defaults shown):

| Factor | Weight | Definition |
|---|---|---|
| need | 0.35 | destination shortage ÷ its predicted demand (capped at 1) |
| quantity_fit | 0.25 | transferable units ÷ source surplus (how much gets used) |
| urgency | 0.20 | 0.6 × (1 − time remaining in destination window) + 0.4 if need ≥ 25 % of demand; full window remains ⇒ low |
| proximity | 0.10 | 1 − distance/max_distance_km (neutral 0.5 when distance unknown) |
| compatibility | 0.10 | same category & meal period 1.0 · same category 0.7 · same period 0.45 · neither 0.2 |

```
score = 100 × Σ weight_i × factor_i        (0–100)
```

Service windows (breakfast 07:30–10:00, lunch 11:30–14:30, dinner
17:00–19:45) drive time-remaining; recommendations for future dates assume
the full window.

## Explanation

Each recommendation ships:
* `factors` — the numeric contribution of every component;
* `reason` — top-3 contributing factors as plain text, e.g.
  *"most of the surplus is usable (+25); compatible item type and meal period (+10); destination shortage risk (+9)"*.

No opaque model produces the score; an operator can recompute it by hand.

## Urgency label

* **High** — urgency factor ≥ 0.55 or destination need ≥ 50 % of demand
* **Medium** — otherwise if total score ≥ 50
* **Low** — otherwise

## Outcome tracking

Every stored recommendation starts `pending`. Operators record
`accepted`/`rejected` plus optional `units_moved` and note via
`POST /api/recommendations/{id}/decision`. Acceptance rate and reported
units redistributed appear in `/api/metrics`. Only accepted-and-reported
transfers count toward impact claims.

## Known simplifications

* Same-item transfers only; no cross-substitution modelling.
* Distances come from a static reference table (`data/distances.csv`);
  no routing or travel-time estimation.
* One transfer per source-destination-item pair per day (greedy allocation).
* Food-safety constraints (holding times, allergens) are out of scope and
  remain staff responsibilities.
