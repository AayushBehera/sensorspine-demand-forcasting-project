# Dataset Compatibility Matrix

What each source can and cannot contribute, and whether/how it joins.
Rule: **no join without a defensible key**; unjoinable layers stay separate.

| Dataset | Granularity | India | Demand signal | Waste/surplus | Context | Joins on | Cannot do |
|---|---|---|---|---|---|---|---|
| HCES 2023-24 Bengaluru | monthly × household × item | yes (1 city) | composition prior only | no | consumption culture | food_category (aggregated) | daily forecasting; location-level ops; never row-joined to operations |
| Swiggy listings | snapshot × restaurant | yes (534 cities) | none (no volumes) | no | price/cuisine mix | city; cuisine→category hints (transparent keyword table) | time series; quantities |
| IFCT 2017 | static × food | yes | none | none | nutrition metadata | food item/category reference only | anything temporal |
| UNEP FWI India | country-year | yes | none | per-capita benchmark | policy context | none (reported as constants) | operational waste prediction |
| ERA5 Bengaluru weather | daily | yes (Bengaluru) | contextual driver | no | temperature/rain features | `date` (exact) | intra-day; other cities |
| Indian holidays | day | yes | calendar driver | no | holiday/festival flags | `date` (exact) | campus-specific events |
| RS-251 food inflation | month-year | yes | price context | no | macro context only | none (reported layer) | demand quantities |
| Market arrivals (Table 5.5) | district-year | yes (Punjab) | supply context | no | market-supply reference | district/year aggregates only | outlet-level ops |
| Crop production / buffer stocks / factories | national/state-year | yes | supply & capacity refs | no | documentation + dashboards | none (reference) | forecasting features |
| UNEP FWI sector table | country-year | India row | none | food-service waste benchmark 28 kg/cap/yr | surplus-engine calibration context | none (benchmark) | operational prediction |
| Online-food survey (Bengaluru) | respondent | yes (Bengaluru) | behaviour rate only | no | demand-behaviour narrative | city aggregate only | time series; quantities |
| Synthetic operations | daily × loc × item × meal | India-styled | YES (target) | YES (planned vs actual) | full operational vars | is the join hub | claims of real-world accuracy |

## Join strategy in code

1. **Weather → operations**: exact `date` key. Real ERA5 rows are used when
   present; gaps fall back to the synthetic seasonal model and are counted in
   `data/context_provenance.json` (`weather_real_rows` / `_synthetic_rows`).
2. **Holidays → operations**: exact `date` key via `app/india_context.py`.
3. **HCES → analytics only**: category value shares are surfaced as a
   *composition prior* (API `/api/data/sources`, dashboard Data tab). They are
   deliberately NOT merged into the training frame — different observational
   unit (household-month vs outlet-day).
4. **Swiggy / IFCT / UNEP**: reference layers for metadata and documentation.
   No automatic joins; any future use must go through explicit, reviewed keys.

## Anti-patterns rejected

* Concatenating household consumption with POS-style transactions into one CSV.
* Converting monthly HCES quantities into pseudo-daily demand.
* Assigning lat/lon to locations without a reliable geocoding source.
* Treating Swiggy "cost" as a transaction quantity.
