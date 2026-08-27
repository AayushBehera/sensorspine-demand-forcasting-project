# Data Sources & Provenance

Every dataset integrated into Sensorspine, with honest provenance labels.
Machine-readable copies live in `data/provenance/dataset_metadata.json`.

Provenance types: **OFFICIAL** (government/standards body) · **RESEARCH**
(academic/institutional) · **COMMUNITY** (scrapes/mirrors, no formal license)
· **SYNTHETIC** (generated here) · **DERIVED** (computed from the above).

---

## Integrated (downloaded & processed)

### 1. HCES 2023-24 Bengaluru household food consumption — OFFICIAL

| Field | Value |
|---|---|
| Source | MoSPI Household Consumption Expenditure Survey 2023-24, unit-level city extract |
| Access path | microdata.gov.in survey microdata mirrored by OpenCity/Oorvani (data.opencity.in) |
| Geographic scope | Bengaluru Urban district households (n = 1,850) |
| Date range | Survey year 2023-24 (monthly recall) |
| Raw file | `data/raw/official/hces2324_bengaluru.zip` (15 level CSVs; Level-5 = food sections 5-6) |
| Processed | `data/processed/consumption/hces_bengaluru_food_items.csv` (85,122 household×item rows), `..._category_shares.csv` |
| License / terms | GoI survey microdata; use per MoSPI *Rider for Users of Unit-Level Data*; cite MoSPI + OpenCity mirror |
| Granularity | monthly per household × item code (PRESERVED — never converted to fake daily data) |
| Intended role | **India consumption composition prior**: value shares by canonical food category |
| Limitations | household acquisition, not cafeteria transactions; single city; item codes partially verified (low-confidence codes flagged in `metadata/hces_item_codes.csv`) |

Item-code mapping was built ONLY from codes transcribed from the official FDQ
Vol-II questionnaire (`data/raw/official/hces_item_codes_raw*.txt`). Codes that
could not be read unambiguously from the PDF are marked `confidence=low` and
mapped to `other`; ambiguous internal aggregates (`092-095`) are excluded from
all aggregations.

### 2. Swiggy restaurant listings, India — COMMUNITY

| Field | Value |
|---|---|
| Source | GitHub mirror of a Kaggle-derived Swiggy listings scrape |
| Geographic scope | 534 Indian cities, 61,425 restaurants |
| Raw file | `data/raw/community/swiggy_india_restaurants.csv` |
| Processed | `data/processed/restaurant/swiggy_restaurants.csv`, `swiggy_cuisine_frequencies.csv` |
| License | None supplied; original copyright Swiggy; educational use only |
| Granularity | restaurant snapshot (undated) |
| Intended role | restaurant/menu metadata: price context, cuisine mix per city |
| Limitations | no transaction volumes; scraper bias; snapshot may be stale |

### 3. IFCT 2017 food composition — RESEARCH (ICMR-NIN)

| Field | Value |
|---|---|
| Source | Indian Food Composition Tables 2017 via the open `ifct2017` project (Zenodo DOI 10.5281/zenodo.7088653) |
| Publisher | ICMR - National Institute of Nutrition, Hyderabad |
| Raw file | `data/raw/research/ifct2017_compositions_index.csv` |
| Processed | `data/processed/metadata/ifct_foods.csv` (542 foods × key nutrients/100 g) |
| License | open republishing by ifct2017 project ("other-open"); cite ICMR-NIN |
| Intended role | food metadata / nutritional enrichment reference |
| Limitations | raw-food compositions; no demand signal |

### 4. UNEP Food Waste Index, India — OFFICIAL-derived (via OWID)

| Field | Value |
|---|---|
| Source | UNEP Food Waste Index through Our World in Data grapher CSV |
| Raw file | `data/raw/official/unep_food_waste_index_owid.csv` (55 countries) |
| Processed | `data/processed/waste/unep_india_food_waste.csv` (India 2019 & 2022) |
| License | OWID CC-BY; underlying UNEP terms apply |
| Intended role | waste-context benchmark (kg/capita: retail / out-of-home / household) |
| Limitations | coarse country-year estimates; not operational |

### 5. Bengaluru daily weather — OFFICIAL-open (Open-Meteo ERA5)

| Field | Value |
|---|---|
| Source | Open-Meteo archive API (ECMWF ERA5 reanalysis), 12.97 N / 77.59 E |
| File | `data/processed/weather/bengaluru_era5_daily.csv` (2025-07-18 → 2026-08-24; refreshed 2026-08-24 via archive API so the full 180-day operational window is real-data covered) |
| License | CC BY 4.0 |
| Intended role | **real contextual demand feature** feeding the operational simulator |
| Limitations | reanalysis estimate, not a station observation |

### 6. Indian public-holiday calendar — DERIVED from official calendars

| Field | Value |
|---|---|
| Source | python `holidays` package (compiled from official gazettes) |
| File | `data/processed/context/india_public_holidays.csv` (53 entries, 2025-2027 incl. Holi, Diwali, Dussehra…) |
| License | MIT (package) |
| Intended role | real festival/holiday flags replacing synthetic ones |
| Limitations | national set only; state gazette holidays not included |

---

## User-collected datasets (integrated 2026-08-22, second batch)

Supplied as local files / kagglehub downloads; originals preserved under
`data/raw/{official,research,community}/` with sha256 in
`data/raw/_user_provenance.json`.

### OFFICIAL — parliamentary answers & national statistics

| Layer | Content | Processed output |
|---|---|---|
| RS-251 AU3123 (Annexure-I) | Monthly y-o-y food-price inflation %, India, 2014-2020 (provisional flags kept) | `processed/context/india_food_inflation_monthly.csv` |
| RS-249 AU2319 | Registered vs operating food-processing factories by State/UT | `processed/institutional/food_processing_capacity_by_state.csv` |
| RS-256 AU392-B | Avg foodgrain stock (MT) in central-pool godowns by year | `processed/institutional/avg_foodgrain_stocks_yearly.csv` |
| Table 5.5 statistical abstract | District × Year market arrivals of food+non-foodgrains, 2007-2018 (786 district-years; unit flagged medium-confidence) | `processed/supply/market_arrivals_district_year.csv` |
| RS-265 AU2108 D-E | National crop production, million tonnes | `processed/supply/crop_production_national.csv` |
| RS-249 AS287-B | State × year quantities — **metric not verifiable from extract**: preserved verbatim with `interpretation_uncertain=true`, excluded from analytics. 2026-08-24 check: values do NOT match the NFSA offtake series (RS US Q.1362); only Bihar/MP/WB present, partial final year — remains excluded | `processed/supply/rs249_as287b_state_year_preserved.csv` |
| HCES 2022-23 Level-4 export (data.gov.in) | 2,516 urban Maharashtra households — **layout DECODED 2026-08-24** from the official `hces2324_layout.xlsx` FDQ Level-04 block (ration-card flags, online-purchase flags, ceremony, meals served, multiplier); original Col 1-20 preserved verbatim; decode recorded via `layout_decoded=true` | `processed/consumption/hces2023_maharashtra_level4_households.csv` |
| HCES factsheet workbook (xlsx) | Official %Composition of MPCE + consumption-level trends across survey years (2011-12 → 2023-24) | `processed/consumption/hces_factsheet_mpce_trend_tidy.csv` |

### RESEARCH / COMMUNITY

| Layer | Content | Processed output |
|---|---|---|
| UNEP FWI country table (kagglehub: joebeachcapital/food-waste) | 214 countries incl. India: household 50 / retail 16 / **food service 28 kg/capita/yr** ("Very Low Confidence" — UNEP's own label, kept) | `processed/waste/unep_fwi_by_country_sectors.csv` |
| Online-food order survey (kagglehub: sudarshan24byte/online-food-dataset; user's identical copy unified) | 388 Bengaluru respondents: demographics → ordered-online outcome (77.6% order rate); demand-behaviour context only | `processed/restaurant/online_food_orders_bangalore.csv` |

### REJECTED after inspection

* **OpenFoodFacts selected-columns extract** (`en.openfoodfacts...csv`) —
  124 rows, **0 usable product names**; an empty sample. Kept at
  `data/raw/community/openfoodfacts_selected_columns_EMPTY.csv` as evidence;
  recorded as REJECTED in quality reports. Not integrated anywhere.

---

## Evaluated but NOT integrated (with reasons)

| Dataset | Verdict | Reason / how to obtain |
|---|---|---|
| HCES 2023-24 all-India microdata | NOT ACCESSIBLE | requires registration on microdata.gov.in; city extract used instead |
| PM POSHAN (mid-day meal) data.gov.in resources | NOT ACCESSIBLE | API returns 403 without a registered data.gov.in api-key; obtain at data.gov.in and place under `data/raw/official/` |
| Zomato Bangalore restaurants (Kaggle) | NOT ACCESSIBLE | Kaggle auth required; Swiggy dataset already fills this role |
| Kaggle "food wastage in restaurant" datasets | REJECTED | unverifiable provenance / likely fabricated values; fails honesty gate |

---

## Synthetic layers (clearly labelled)

* Operational campus transactions — `app/data_generator.py` v2.0-india-context,
  `is_synthetic=true` on every row, generator version + scenario stamped.
  See [synthetic-data.md](synthetic-data.md).
* Redistribution scenarios — `data/synthetic/operational/redistribution_scenarios.json`
  (12 deterministic cases). See [data-pipeline.md](data-pipeline.md).
