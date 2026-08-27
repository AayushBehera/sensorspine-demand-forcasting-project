# Synthetic Data — rules, labelling, scenarios

## Why synthetic operational data exists

Sensorspine's core loop needs campus-level transactions (planned production vs
actual demand per outlet/item/meal). No such dataset is published for Indian
campuses. The prototype therefore SIMULATES operations deterministically while
every *context* input is real. This separation is explicit everywhere.

## Labelling contract

Every generated service row carries:

```
is_synthetic = true
synthetic_generator_version = 2.0-india-context
simulation_scenario = campus_baseline
```

Context provenance for the whole dataset is written to
`data/context_provenance.json` and exposed via `GET /api/meta`
(`context_provenance`) and `GET /api/data/sources`:

```
weather_real_rows / weather_synthetic_rows   # how much context was real
holidays_matched                             # real Indian holidays in window
```

Synthetic records are NEVER mixed into real-world evaluation claims.

## Generation model (deterministic, seed-controlled)

```
base demand = 120 units × location scale × item-period popularity
× calendar factor     (real holidays ÷ term/exam/break events)
× weekday factor      (weekend: dining halls quieter, sports canteen busier)
× weather factor      (REAL ERA5 temp/rain: rain −8% food, +5% beverages;
                       hot days boost cold/beverage items)
× promotion factor    (+22%, ~10% of item-days)
× lognormal noise     (σ=0.13)
+ event spikes        (4% of sports-canteen days ×1.5-2.2)

planned production = EWMA(0.7) of past demand × U(1.02,1.18) safety buffer
                    → organically creates surpluses AND shortages
```

Academic calendar (terms, breaks, exams) remains synthetic by design — no real
campus calendar exists here; it is labelled as simulation structure.

## Redistribution scenarios (12, deterministic)

`data_pipeline/scenarios.py` → `data/synthetic/operational/redistribution_scenarios.json`

| Scenario | Expected engine behaviour |
|---|---|
| normal_day | no transfers (all near-balanced) |
| weekend_busy / weekend_quiet | pattern shift, no action |
| holiday_low_demand (real calendar) | collapse in demand → over-supply risk |
| festival_spike | shortages everywhere → nothing to move |
| campus_event | donor hall + event shortage → ≥1 transfer |
| weather_disruption (monsoon) | kiosk collapses, sheltered hall short → transfer |
| overproduction | waste-risk visible, no eligible dest → 0 recs |
| shortage_everywhere | nothing to give → 0 recs |
| redistribution_opportunity | canonical case → 1 high-score rec |
| no_eligible_destination | surplus stranded → 0 recs |
| multiple_candidates | 2 destinations; greedy allocation caps at need (110 of 140) |

Tests: `tests/test_data_integration.py::test_*scenario*`.
