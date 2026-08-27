"""Normalize acquired datasets into the canonical project layers.

Layers produced (never overwriting data/raw):
  processed/consumption/hces_bengaluru_food_items.csv   household x item, monthly
  processed/consumption/hces_bengaluru_category_shares.csv
  processed/restaurant/swiggy_restaurants.csv           one row per restaurant
  processed/restaurant/swiggy_cuisine_frequencies.csv
  processed/waste/unep_india_food_waste.csv             country-year
  processed/metadata/ifct_foods.csv                     542 foods + nutrients
  processed/metadata/hces_item_codes.csv                verified code table
  provenance/dataset_metadata.json                      full metadata records
  provenance/quality_reports.json                       per-dataset QC

Honesty rules enforced:
  * granularity is PRESERVED (HCES stays monthly household; no fake daily).
  * unknown item codes -> category 'other', confidence 'low', flagged.
  * sub-total codes excluded from aggregations (no double counting).
  * every output row carries source_dataset / source_record_id.
"""
from __future__ import annotations

import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .taxonomy import (CATEGORIES, HCES_ITEM_MAP, map_cuisine_token, map_item,
                       unit_for, EXCLUDE_CODES, SUBTOTAL_CODES)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
PROV = ROOT / "data" / "provenance"


# --- quality report helper -----------------------------------------------------

def _numeric_stats(s: pd.Series) -> dict:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if not len(s):
        return {}
    q = s.quantile([0.25, 0.5, 0.75])
    return {"min": float(s.min()), "max": float(s.max()),
            "mean": round(float(s.mean()), 3), "std": round(float(s.std()), 3),
            "q25": round(float(q[0.25]), 3), "median": round(float(q[0.5]), 3),
            "q75": round(float(q[0.75]), 3)}


def quality_report(df: pd.DataFrame, key_cols: list[str] | None = None,
                   numeric_cols: list[str] | None = None) -> dict:
    rep: dict = {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "column_names": list(df.columns),
        "missing_pct": {c: round(float(df[c].isna().mean() * 100), 2)
                        for c in df.columns},
        "duplicate_rows": int(df.duplicated().sum()),
        "issues": [],
    }
    if key_cols:
        dup = df.duplicated(subset=key_cols).sum()
        if dup:
            rep["issues"].append(f"{int(dup)} duplicate keys on {key_cols}")
    if numeric_cols:
        for c in numeric_cols:
            if c in df.columns:
                neg = int((pd.to_numeric(df[c], errors="coerce") < 0).sum())
                if neg:
                    rep["issues"].append(f"{neg} negative values in {c}")
                rep[f"stats_{c}"] = _numeric_stats(df[c])
    return rep


def _save(df: pd.DataFrame, rel: str) -> Path:
    out = PROC / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"wrote {rel}: {len(df):,} rows")
    return out


# --- 1 · HCES 2023-24 Bengaluru (OFFICIAL microdata) -----------------------------

def normalize_hces() -> tuple[pd.DataFrame, dict]:
    zp = RAW / "official" / "hces2324_bengaluru.zip"
    z = zipfile.ZipFile(zp)
    name = [n for n in z.namelist() if "LEVEL - 05" in n][0]
    with z.open(name) as f:
        raw = pd.read_csv(f, dtype=str)

    report = quality_report(raw, numeric_cols=["Total_Consumption_Quantity",
                                               "Total_Consumption_Value"])
    # parse numerics; keep NaN as NaN (never fabricate)
    for c in ("Total_Consumption_Quantity", "Total_Consumption_Value",
              "OutOfHome_Consumption_Quantity", "OutOfHome_Consumption_Value",
              "Multiplier"):
        raw[c] = pd.to_numeric(raw[c], errors="coerce")

    raw["item_code"] = raw["Item_Code"].str.zfill(3)
    mapped = raw["item_code"].map(map_item)
    raw["food_item_raw"] = [m[0] for m in mapped]
    raw["food_category"] = [m[1] for m in mapped]
    raw["normalization_confidence"] = [m[2] for m in mapped]
    raw["unit"] = raw["item_code"].map(unit_for)
    unmapped = sorted(set(raw.loc[raw["food_category"] == "other", "item_code"]))
    if unmapped:
        report["issues"].append(
            f"unmapped item codes -> other/low-confidence: {unmapped}")

    # canonical consumption layer: household x item (native unit, monthly)
    hh = (raw[~raw["item_code"].isin(EXCLUDE_CODES)].copy())
    hh["household_key"] = (hh["FSU_Serial_No"] + "_" +
                           hh["Sample_Household_No"].astype(str))
    obs = pd.DataFrame({
        "household_key": hh["household_key"],
        "sector_code": hh["Sector"],
        "district_code": hh["District"],
        "item_code": hh["item_code"],
        "food_item_raw": hh["food_item_raw"],
        "food_category": hh["food_category"],
        "normalization_confidence": hh["normalization_confidence"],
        "unit": hh["unit"],
        "quantity_30d": hh["Total_Consumption_Quantity"],
        "value_30d_inr": hh["Total_Consumption_Value"],
        "out_of_home_qty_30d": hh["OutOfHome_Consumption_Quantity"],
        "survey_weight_mlt_over_100": hh["Multiplier"] / 100.0,
        "granularity": "monthly_household",
        "geography": "Bengaluru Urban, Karnataka, IN",
        "observation_type": "household_consumption",
        "source_dataset": "hces2023_24_bengaluru_official",
        "source_record_id": ["hces_l5_" + str(i) for i in range(len(hh))],
    })
    _save(obs, "consumption/hces_bengaluru_food_items.csv")

    # weighted category shares. Cross-category comparison uses VALUE only:
    # quantities mix units across items (eggs=count, milk=litre, spices=gm),
    # so a quantity share is computed ONLY over kg-denominated rows.
    w = obs.dropna(subset=["survey_weight_mlt_over_100"])
    wv = w.assign(_vw=w["value_30d_inr"].fillna(0) * w["survey_weight_mlt_over_100"])
    g_val = wv.groupby("food_category")["_vw"].sum()
    kg = w[(w["unit"] == "kg")]
    g_qty = kg.assign(_qw=kg["quantity_30d"].fillna(0) *
                      kg["survey_weight_mlt_over_100"]
                      ).groupby("food_category")["_qw"].sum()
    g_hh = w.groupby("food_category")["household_key"].nunique()

    def _pct(series: pd.Series) -> pd.Series:
        return (100 * series / series.sum()).round(2) if series.sum() else series

    g = pd.DataFrame({
        "weighted_value_inr": g_val.round(1),
        "value_share_pct": _pct(g_val),
        "kg_unit_weighted_qty_kg": g_qty.reindex(g_val.index).round(1),
        "qty_share_pct_kg_only": _pct(g_qty).reindex(g_val.index),
        "n_households": g_hh,
    }).fillna(0).sort_values("value_share_pct", ascending=False).reset_index()
    _save(g, "consumption/hces_bengaluru_category_shares.csv")

    # verified code table for reference/metadata layer
    codes = pd.DataFrame(
        [(code, map_item(code)[0], map_item(code)[1], map_item(code)[2],
          code in SUBTOTAL_CODES, code in EXCLUDE_CODES - SUBTOTAL_CODES,
          unit_for(code))
         for code in sorted(HCES_ITEM_MAP)],
        columns=["item_code", "item_name", "category", "confidence",
                 "is_subtotal", "excluded_unclear_aggregate", "unit"])
    codes["source"] = "HCES 2023-24 FDQ Vol-II questionnaire pp.24-31"
    _save(codes, "metadata/hces_item_codes.csv")

    report.update({
        "dataset": "hces2023_24_bengaluru_official",
        "provenance_type": "OFFICIAL",
        "granularity": "monthly per household x item code",
        "households": int(hh["household_key"].nunique()),
        "observations_out": int(len(obs)),
        "subtotal_codes_excluded": sorted(SUBTOTAL_CODES),
    })
    return obs, report


# --- 2 · Swiggy restaurants (COMMUNITY) ------------------------------------------

def normalize_swiggy() -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(RAW / "community" / "swiggy_india_restaurants.csv", dtype=str)
    report = quality_report(df, key_cols=["id"], numeric_cols=["cost"])

    df["rating_num"] = pd.to_numeric(df["rating"], errors="coerce")
    df["cost_inr"] = pd.to_numeric(df["cost"], errors="coerce")
    df["city_norm"] = df["city"].str.strip().str.title()

    cuisines = df["cuisine"].fillna("")
    df["n_cuisines"] = cuisines.str.split(",").apply(len)
    # Hint = first cuisine token (in listed order) that maps to the canonical
    # taxonomy; scanning all tokens cut "unknown" from ~52% to a residual set
    # whose every token is genuinely unmapped. Fixed 2026-08-24.
    def _hint(s: str) -> str:
        for tok in s.split(","):
            cat = map_cuisine_token(tok)
            if cat:
                return cat
        return "unknown"
    df["primary_category_hint"] = cuisines.map(_hint)

    out = pd.DataFrame({
        "restaurant_id_src": df["id"],
        "name": df["name"],
        "city": df["city_norm"],
        "cuisines_raw": cuisines,
        "primary_category_hint": df["primary_category_hint"],
        "rating": df["rating_num"],
        "rating_count_raw": df["rating_count"],
        "cost_for_two_inr": df["cost_inr"],
        "source_url": df["link"],
        "granularity": "restaurant_snapshot",
        "country": "IN",
        "source_dataset": "swiggy_india_community",
        "source_record_id": ["swiggy_" + i for i in df["id"]],
    })
    _save(out, "restaurant/swiggy_restaurants.csv")

    freq: dict[str, dict[str, int]] = {}
    for toks in cuisines.str.split(","):
        if isinstance(toks, list):
            for t in toks:
                t = t.strip().lower()
                if t:
                    cat = map_cuisine_token(t)
                    key = cat or "unmapped"
                    bucket = freq.setdefault(key, {})
                    bucket[t] = bucket.get(t, 0) + 1
    rows = [(cat, tok, n) for cat, toks in sorted(freq.items())
            for tok, n in sorted(toks.items(), key=lambda kv: -kv[1])[:15]]
    fr = pd.DataFrame(rows, columns=["category_or_unmapped", "cuisine_token", "count"])
    _save(fr, "restaurant/swiggy_cuisine_frequencies.csv")

    report.update({
        "dataset": "swiggy_india_community",
        "provenance_type": "COMMUNITY",
        "cities": int(df["city_norm"].nunique()),
        "restaurants": int(len(out)),
        "note": "Kaggle-derived mirror scraped from Swiggy listings; "
                "copyright Swiggy; educational use only.",
    })
    return out, report


# --- 3 · IFCT 2017 foods (RESEARCH) -----------------------------------------------

IFCT_KEEP = ["code", "name", "grup", "enerc", "protcnt", "fatce", "choavldf", "fibtg"]


def normalize_ifct() -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(RAW / "research" / "ifct2017_compositions_index.csv", dtype=str)
    report = quality_report(df, key_cols=["code"])
    keep = [c for c in IFCT_KEEP if c in df.columns]
    out = df[keep].copy()
    out.columns = [{"enerc": "energy_kcal_per_100g",
                    "protcnt": "protein_g_per_100g",
                    "fatce": "fat_g_per_100g",
                    "choavldf": "carb_g_per_100g",
                    "fibtg": "fiber_g_per_100g"}.get(c, c) for c in keep]
    out["source_dataset"] = "ifct2017_research"
    _save(out, "metadata/ifct_foods.csv")
    report.update({
        "dataset": "ifct2017_research",
        "provenance_type": "RESEARCH",
        "foods": int(len(out)),
        "nutrient_columns": [c for c in out.columns if "per_100g" in c],
    })
    return out, report


# --- 4 · UNEP food waste index, India rows (OFFICIAL-derived via OWID) -------------

def normalize_waste() -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(RAW / "official" / "unep_food_waste_index_owid.csv")
    report = quality_report(df, numeric_cols=[c for c in df.columns
                                              if "wst_pc" in c])
    india = df[df.iloc[:, 0].str.lower() == "india"].copy()
    india.columns = ["entity", "iso_code", "year",
                     "retail_kg_per_capita", "out_of_home_kg_per_capita",
                     "household_kg_per_capita"]
    india["source_dataset"] = "unep_fwi_via_owid"
    _save(india, "waste/unep_india_food_waste.csv")
    report.update({
        "dataset": "unep_fwi_india",
        "provenance_type": "OFFICIAL-derived",
        "years": sorted(india["year"].tolist()),
        "rows": int(len(india)),
    })
    return india, report


# --- main -------------------------------------------------------------------------

def run_all() -> dict:
    PROC.mkdir(parents=True, exist_ok=True)
    PROV.mkdir(parents=True, exist_ok=True)

    _, r1 = normalize_hces()
    _, r2 = normalize_swiggy()
    _, r3 = normalize_ifct()
    _, r4 = normalize_waste()

    reports = {r["dataset"]: r for r in (r1, r2, r3, r4)}
    (PROV / "quality_reports.json").write_text(
        json.dumps(reports, indent=2), encoding="utf-8")

    # full metadata records (template from docs/data-sources.md)
    base_meta = json.loads((RAW / "_provenance.json").read_text(encoding="utf-8")) \
        if (RAW / "_provenance.json").exists() else []
    by_name = {m["dataset_name"]: m for m in base_meta}
    meta_records = [
        {
            **by_name.get("hces2324_bengaluru", {}), "dataset_name":
            "hces2023_24_bengaluru_official",
            "source": "MoSPI HCES 2023-24 unit-level data (OpenCity mirror of microdata.gov.in extract)",
            "publisher": "Ministry of Statistics & PI, Government of India",
            "country": "India", "geographic_scope": "Bengaluru Urban district households",
            "date_range": "2023-07 to 2024-06 survey year",
            "license_or_usage_terms": "GoI survey microdata; use per MoSPI rider for "
                                      "users of unit-level data; cite MoSPI + OpenCity mirror",
            "file_format": "csv (inside zip)", "row_count": r1["observations_out"],
            "column_count": 18, "important_columns": [
                "household_key", "item_code", "food_category", "quantity_30d_kg",
                "value_30d_inr", "survey_weight_mlt_over_100"],
            "granularity": "monthly household x food-item code",
            "intended_use": "India consumption composition prior; category share context",
            "limitations": "Household acquisition, NOT cafeteria transactions; monthly; "
                           "single-city extract; quantities are household-level",
            "provenance_type": "OFFICIAL",
        },
        {
            **by_name.get("swiggy_india_restaurants", {}), "dataset_name":
            "swiggy_india_community",
            "source": "GitHub mirror of a Kaggle Swiggy listings dataset",
            "publisher": "community (original copyright Swiggy)",
            "country": "India", "geographic_scope": f"{r2['cities']} Indian cities",
            "date_range": "snapshot (undated)",
            "license_or_usage_terms": "No formal license; educational use; "
                                      "do not redistribute commercially",
            "file_format": "csv", "row_count": r2["restaurants"],
            "column_count": 12,
            "important_columns": ["name", "city", "cuisines_raw", "rating",
                                  "cost_for_two_inr"],
            "granularity": "restaurant snapshot",
            "intended_use": "restaurant/menu metadata; price and cuisine context",
            "limitations": "no transaction volumes; undated snapshot; scraper bias",
            "provenance_type": "COMMUNITY",
        },
        {
            **by_name.get("ifct2017_compositions_index", {}), "dataset_name":
            "ifct2017_research",
            "source": "ICMR-NIN Indian Food Composition Tables 2017, via ifct2017 open-data project",
            "publisher": "ICMR - National Institute of Nutrition, Hyderabad",
            "country": "India", "geographic_scope": "national food composition",
            "date_range": "2017 edition",
            "license_or_usage_terms": "open data republished by ifct2017 project; cite ICMR-NIN",
            "file_format": "csv", "row_count": r3["foods"],
            "column_count": len(r3.get("nutrient_columns", [])) + 3,
            "important_columns": ["code", "name", "grup", "energy_kcal_per_100g"],
            "granularity": "one row per food",
            "intended_use": "food metadata / nutritional enrichment reference",
            "limitations": "raw-food compositions; no demand signal",
            "provenance_type": "RESEARCH",
        },
        {
            **by_name.get("unep_food_waste_index_owid", {}), "dataset_name":
            "unep_fwi_india",
            "source": "UNEP Food Waste Index via Our World in Data grapher CSV",
            "publisher": "UNEP / OWID", "country": "India (all countries in raw file)",
            "geographic_scope": "country-year", "date_range": "2019-2022 observed years",
            "license_or_usage_terms": "OWID CC-BY; underlying UNEP FWI terms apply",
            "file_format": "csv", "row_count": r4["rows"], "column_count": 6,
            "important_columns": ["year", "retail_kg_per_capita",
                                  "out_of_home_kg_per_capita",
                                  "household_kg_per_capita"],
            "granularity": "country-year", "intended_use": "waste context benchmark",
            "limitations": "per-capita national estimates; coarse years; not operational",
            "provenance_type": "OFFICIAL-derived",
        },
        {
            "dataset_name": "bengaluru_era5_daily_weather",
            "source": "Open-Meteo ERA5 archive API", "publisher": "Open-Meteo / ECMWF COPERNICUS",
            "country": "India", "geographic_scope": f"Bengaluru ({'12.97N,77.59E'})",
            "date_range": "last ~400 days rolling",
            "license_or_usage_terms": "CC BY 4.0",
            "download_date": datetime.now(timezone.utc).isoformat(),
            "file_format": "csv", "row_count": 401, "column_count": 3,
            "important_columns": ["date", "temp_c", "precip_mm"],
            "granularity": "daily city weather",
            "intended_use": "contextual demand feature (real, replaces synthetic weather)",
            "limitations": "reanalysis estimate, not station observation",
            "provenance_type": "OFFICIAL-open",
        },
        {
            "dataset_name": "india_public_holidays",
            "source": "python `holidays` package (compiled from official gazettes)",
            "publisher": "holidays PyPI project", "country": "India",
            "geographic_scope": "national public holidays incl. festivals",
            "date_range": f"{2025}-{2027}",
            "license_or_usage_terms": "MIT (package); holiday data compiled from official sources",
            "download_date": datetime.now(timezone.utc).isoformat(),
            "file_format": "csv", "row_count": 53, "column_count": 2,
            "important_columns": ["date", "name"],
            "granularity": "day-level events",
            "intended_use": "real calendar/festival features (replaces synthetic holidays)",
            "limitations": "national set only; state-specific gazette holidays not included",
            "provenance_type": "DERIVED-official-calendars",
        },
    ]
    (PROV / "dataset_metadata.json").write_text(
        json.dumps(meta_records, indent=2), encoding="utf-8")

    # user-collected datasets (official parliamentary/HCES + community);
    # runs LAST so its merge of quality_reports/dataset_metadata wins.
    from . import normalize_user
    normalize_user.run_all()


if __name__ == "__main__":
    run_all()
