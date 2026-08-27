# Data Dictionary — canonical layers

Every processed record carries `source_dataset` and (where meaningful)
`source_record_id`. Missing information is `null`/`UNKNOWN` — never invented.

## ConsumptionObservation (`processed/consumption/hces_bengaluru_food_items.csv`)

| Column | Type | Notes |
|---|---|---|
| household_key | str | FSU serial + household no. |
| sector_code / district_code | int | HCES geography codes |
| item_code | str(3) | official HCES 2023-24 code |
| food_item_raw | str | verified questionnaire label, else `unknown` |
| food_category | enum | see taxonomy below |
| normalization_confidence | high/medium/low | low = flagged for review |
| unit | kg/litre/number/gram | native survey unit — never mixed in sums |
| quantity_30d | float | monthly quantity in `unit` |
| value_30d_inr | float | monthly spend ₹ (comparable across units) |
| out_of_home_qty_30d | float | away-from-home portion |
| survey_weight_mlt_over_100 | float | design weight (MLT/100 per MoSPI readme) |
| granularity | constant | `monthly_household` |

## CategoryShare (`processed/consumption/hces_bengaluru_category_shares.csv`)

weighted_value_inr · value_share_pct · kg_unit_weighted_qty_kg (kg rows only) ·
qty_share_pct_kg_only · n_households.

## RestaurantRecord (`processed/restaurant/swiggy_restaurants.csv`)

restaurant_id_src · name · city · cuisines_raw · primary_category_hint
(first cuisine token that maps to the canonical taxonomy, scanning all tokens;
`unknown` only when every token is unmapped) · rating · rating_count_raw ·
cost_for_two_inr · source_url · provenance COMMUNITY.

## MaharashtraHouseholdLevel4 (`processed/consumption/hces2023_maharashtra_level4_households.csv`)

HCES 2022-23 Level-4, 2,516 urban Maharashtra households. Layout DECODED
2026-08-24 from the official `hces2324_layout.xlsx` FDQ Level-04 block; the
original `col_1..col_20` columns are preserved verbatim alongside named
duplicates (`layout_decoded=true` on every row):

| Named column | Source col | Meaning |
|---|---|---|
| ration_card_procured_flag / ration_card_procured | col_1 | 1 = yes, 2 = no (PDS purchase in last 30 days) |
| ration_item_rice/wheat/coarse_grain/sugar/pulses/edible_oil/other_food_flag | col_2–col_8 | 1 = ticked, blank otherwise |
| online_purchase_groceries/milk_dairy/vegetables/fresh_fruits/dry_fruits/egg_fish_meat/served_processed/packed_processed/other_food_flag | col_9–col_17 | 1 = ticked, blank otherwise |
| ceremony_performed_code | col_18 | 1/2 code (FDQ 4.1.4) |
| meals_served_nonhousehold_30d | col_19 | count (FDQ 4.1.5) |
| survey_multiplier_mlt | col_20 | design multiplier |

Cross-check against the official MoSPI Level-4 documentation is recommended
before heavy analytical use (`layout_decoded` records this provenance).

## WasteContext (`processed/waste/unep_india_food_waste.csv`)

year · retail_kg_per_capita · out_of_home_kg_per_capita ·
household_kg_per_capita.

## FoodMetadata (`processed/metadata/ifct_foods.csv`)

code · name · grup · energy_kcal_per_100g · protein_g_per_100g · fat_g_per_100g
· carb_g_per_100g · fiber_g_per_100g.

## ItemCodeReference (`processed/metadata/hces_item_codes.csv`)

item_code · item_name · category · confidence · is_subtotal ·
excluded_unclear_aggregate · unit · source.

## Operational records (SYNTHETIC — `data/raw_service_records.csv`)

date · location_id · item_id · category · meal_period · planned_production ·
actual_demand · promotion · **is_synthetic=true** ·
synthetic_generator_version · simulation_scenario.

## Canonical categories

rice_cereals · wheat_breads · dal_pulses · vegetables · fruits · dairy · egg ·
fish · chicken_meat · oils_fats · sugar_sweets · salt · spices · beverages ·
served_processed · other.
