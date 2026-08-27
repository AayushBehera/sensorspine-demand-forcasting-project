"""Normalize user-collected datasets into canonical layers.

Every output preserves original granularity, flags uncertain interpretation
explicitly, and carries source_dataset / source_record_id. Nothing here
invents values: unknowns stay null or are flagged.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .normalize import PROC, RAW, PROV, _save, quality_report


def _load(name: str) -> Path:
    hits = list(RAW.rglob(name))
    if not hits:
        raise FileNotFoundError(f"{name} not found under data/raw")
    return hits[0]


def _user_prov() -> list[dict]:
    p = RAW / "_user_provenance.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


# --- OFFICIAL parliamentary answers ----------------------------------------------

def food_inflation_monthly() -> tuple[pd.DataFrame, dict]:
    """RS-251: monthly y-o-y food-price inflation, India, 2014-2020."""
    df = pd.read_csv(_load("rs251_monthly_food_inflation.csv"))
    rep = quality_report(df)
    long = df.melt(id_vars="Month", var_name="year", value_name="inflation_pct")
    long["provisional"] = long["inflation_pct"].astype(str).str.contains(r"\(P\)")
    long["inflation_pct"] = pd.to_numeric(
        long["inflation_pct"].astype(str).str.replace(r"\(P\)", "", regex=True),
        errors="coerce")
    long = long.rename(columns={"Month": "month"}).dropna(
        subset=["inflation_pct"])
    long["source_dataset"] = "rs251_food_inflation_official"
    long["country"] = "IN"
    long["observation_type"] = "yoy_food_price_inflation"
    _save(long, "context/india_food_inflation_monthly.csv")
    rep.update({"dataset": "rs251_food_inflation_official",
                "rows": int(len(long)),
                "note": "NA cells dropped (survey months not published); "
                        "(P) = provisional kept flagged"})
    return long, rep


def factories_by_state() -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(_load("rs249_food_processing_factories_by_state.csv"))
    rep = quality_report(df, numeric_cols=["Factories in Operation (No.) at 2 digit of NIC"])
    df = df.drop(columns=["S.No."], errors="ignore")
    df.columns = ["state_ut", "factories_registered", "factories_operating"]
    for c in ("factories_registered", "factories_operating"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df["source_dataset"] = "rs249_factories_official"
    _save(df, "institutional/food_processing_capacity_by_state.csv")
    rep.update({"dataset": "rs249_factories_official", "rows": int(len(df))})
    return df, rep


def buffer_stocks() -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(_load("rs256_avg_foodgrain_stocks.csv"))
    rep = quality_report(df, numeric_cols=[df.columns[1]])
    df.columns = ["year", "avg_stock_mt_central_pool"]
    df["avg_stock_mt_central_pool"] = pd.to_numeric(
        df["avg_stock_mt_central_pool"], errors="coerce")
    df["source_dataset"] = "rs256_stocks_official"
    _save(df, "institutional/avg_foodgrain_stocks_yearly.csv")
    rep.update({"dataset": "rs256_stocks_official", "rows": int(len(df))})
    return df, rep


def market_arrivals() -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(_load("table5_5_market_arrivals_district_year.csv"))
    rep = quality_report(raw)
    year_cols = [c for c in raw.columns if str(c).strip() != "District/Year"]
    long = raw.melt(id_vars=["District/Year"], value_vars=year_cols,
                    var_name="year", value_name="arrivals_qty")
    long = long.rename(columns={"District/Year": "district"})
    long["arrivals_qty"] = pd.to_numeric(
        long["arrivals_qty"].astype(str).str.replace(",", ""), errors="coerce")
    n_na = int(long["arrivals_qty"].isna().sum())
    if n_na:
        rep["issues"].append(f"{n_na} NA arrival values dropped (unreported)")
    long = long.dropna(subset=["arrivals_qty"])
    long["unit"] = "tonnes"       # per Table 5.5 abstract; flagged below
    long["unit_confidence"] = "medium"   # unit label not present in extract
    long["commodity_group"] = "foodgrains_and_non_foodgrains_total"
    long["source_dataset"] = "market_arrivals_official"
    _save(long, "supply/market_arrivals_district_year.csv")
    rep.update({"dataset": "market_arrivals_official", "rows": int(len(long)),
                "districts": int(long['district'].nunique()),
                "years": sorted(long['year'].astype(int).unique().tolist())})
    return long, rep


def crop_production_national() -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(_load("rs265_crop_production_national.csv"))
    rep = quality_report(df, numeric_cols=[c for c in df.columns if "Production" in c])
    df.columns = ["sl_no", "crop", "production_mt"][: len(df.columns)]
    df["production_mt"] = pd.to_numeric(df["production_mt"], errors="coerce")
    df["source_dataset"] = "rs265_crop_production_official"
    _save(df, "supply/crop_production_national.csv")
    rep.update({"dataset": "rs265_crop_production_official", "rows": int(len(df))})
    return df, rep


def as287b_state_year() -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(_load("rs249_as287b_state_year_unverified_metric.csv"))
    rep = quality_report(df)
    df.columns = [str(c).strip() for c in df.columns]
    df["interpretation_uncertain"] = True   # metric not verifiable from extract
    df["source_dataset"] = "rs249_as287b_unverified"
    _save(df, "supply/rs249_as287b_state_year_preserved.csv")
    rep.update({"dataset": "rs249_as287b_unverified", "rows": int(len(df)),
                "issues": ["metric definition not verifiable from extract; "
                           "preserved verbatim, excluded from analytics"]})
    return df, rep


# --- HCES official aggregates ------------------------------------------------------

def hces_maharashtra_level4() -> tuple[pd.DataFrame, dict]:
    """HCES 2022 Level-4 rows (one per urban Maharashtra household).

    Columns are generic Col1..Col20 from the data.gov.in export; without the
    official Level-4 layout we preserve verbatim and DO NOT interpret.
    """
    df = pd.read_csv(_load("hces2023_maharashtra_level4_unit_data.csv"), dtype=str)
    rep = quality_report(df)
    keep_id = ["Year", "FSU Serial No.", "Sector", "State", "Region", "District",
               "Stratum", "Sub-stratum", "Panel", "Sub-sample", "FOD-Sub-Region",
               "Sample SU No.", "Sample Sub-division no.",
               "Second-stage-stratum no.", "Sample hhld. No.", "Questionnaire No.",
               "Level"]
    out = df[keep_id + [c for c in df.columns if c.startswith("Col ")]].copy()
    out.columns = [c.lower().replace(".", "").replace(" ", "_") for c in out.columns]
    out["household_key"] = (out["fsu_serial_no"] + "_" + out["sample_hhld_no"])
    out["interpretation_uncertain"] = True
    out["geography"] = "Maharashtra urban (state code 27)"
    out["granularity"] = "annual_household"
    out["source_dataset"] = "hces2023_maharashtra_level4_official"
    out["source_record_id"] = df["_id"]
    _save(out, "consumption/hces2023_maharashtra_level4_households.csv")
    rep.update({
        "dataset": "hces2023_maharashtra_level4_official",
        "households": int(out["household_key"].nunique()),
        "issues": ["Level-4 layout not available; Col1-Col20 preserved "
                   "verbatim without interpretation"],
    })
    return out, rep


def hces_factsheet_tables() -> tuple[pd.DataFrame, dict]:
    """Official MoSPI factsheet workbook -> tidy MPCE composition trend."""
    import openpyxl

    xp = _load("hces2324_factsheet_tables.xlsx")
    wb = openpyxl.load_workbook(xp, read_only=True, data_only=True)
    frames = []
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        rows = [[("" if v is None else v) for v in row]
                for row in ws.iter_rows(values_only=True)]
        if not rows:
            continue
        header = [str(h).strip() for h in rows[0]]
        df = pd.DataFrame(rows[1:], columns=header)
        df.insert(0, "factsheet_table", sheet)
        frames.append(df)
    tidy = pd.concat(frames, ignore_index=True, sort=False)
    # drop fully-empty rows/columns
    tidy = tidy.dropna(how="all").dropna(axis=1, how="all")
    rep = quality_report(tidy)
    tidy["source_dataset"] = "hces2324_factsheet_official"
    _save(tidy, "consumption/hces_factsheet_mpce_trend_tidy.csv")
    rep.update({"dataset": "hces2324_factsheet_official",
                "tables": wb.sheetnames, "rows": int(len(tidy)),
                "note": "%Composition of MPCE by item across survey years "
                        "(2011-12 .. 2023-24) - consumption-context series"})
    return tidy, rep


# --- COMMUNITY ---------------------------------------------------------------------

def online_food_survey() -> tuple[pd.DataFrame, dict]:
    """Bangalore online-food order survey (Kaggle; duplicate copy unified)."""
    df = pd.read_csv(_load("onlinefoods_bangalore_survey.csv"))
    rep = quality_report(df, key_cols=None,
                         numeric_cols=["Age", "Family size", "latitude", "longitude"])
    df = df.loc[:, ~df.columns.str.match(r"Unnamed")]
    df.columns = ["age", "gender", "marital_status", "occupation",
                  "monthly_income", "education", "family_size", "latitude",
                  "longitude", "pin_code", "ordered_online", "feedback_sentiment"]
    df["ordered_online"] = df["ordered_online"].map({"Yes": True, "No": False})
    df["city"] = "Bengaluru"
    df["country"] = "IN"
    df["granularity"] = "respondent_survey"
    df["source_dataset"] = "onlinefoods_bangalore_community"
    df["source_record_id"] = ["onf_" + str(i) for i in range(len(df))]
    _save(df, "restaurant/online_food_orders_bangalore.csv")
    rate = round(100 * float(df["ordered_online"].mean()), 1)
    rep.update({"dataset": "onlinefoods_bangalore_community",
                "respondents": int(len(df)),
                "order_rate_pct": rate,
                "note": "demand-behaviour context only; NOT transactions"})
    return df, rep


def unep_fwi_sectors() -> tuple[pd.DataFrame, dict]:
    """UNEP FWI country table incl. sector splits (food service!)."""
    df = pd.read_csv(_load("unep_food_waste_by_country_kaggle.csv"))
    rep = quality_report(df, numeric_cols=[
        "combined figures (kg/capita/year)",
        "Food service estimate (kg/capita/year)"])
    df.columns = ["country", "combined_kg_pc_yr", "household_kg_pc_yr",
                  "household_t_yr", "retail_kg_pc_yr", "retail_t_yr",
                  "food_service_kg_pc_yr", "food_service_t_yr",
                  "confidence", "m49_code", "region", "reference"]
    df["is_india"] = df["country"].str.lower() == "india"
    df["source_dataset"] = "unep_fwi_sectors_research"
    _save(df, "waste/unep_fwi_by_country_sectors.csv")
    india = df[df["is_india"]].iloc[0]
    rep.update({
        "dataset": "unep_fwi_sectors_research",
        "countries": int(len(df)),
        "india_food_service_kg_pc_yr": float(india["food_service_kg_pc_yr"]),
        "india_combined_kg_pc_yr": float(india["combined_kg_pc_yr"]),
        "confidence_india": india["confidence"],
        "note": "supersedes OWID series for sector split; UNEP via Kaggle",
    })
    return df, rep


def openfoodfacts_extract() -> tuple[pd.DataFrame, dict]:
    """User's OpenFoodFacts extract: verify emptiness honestly."""
    path = _load("openfoodfacts_selected_columns_EMPTY.csv")
    df = pd.read_csv(path, low_memory=False)
    rep = quality_report(df)
    named = int(df["product_name"].notna().sum()) if "product_name" in df else 0
    rep.update({"dataset": "openfoodfacts_extract", "rows": int(len(df)),
                "usable_product_rows": named,
                "status": "REJECTED - extract contains no usable products"})
    return df, rep


# --- main --------------------------------------------------------------------------

def run_all() -> dict:
    results = [
        food_inflation_monthly(),
        factories_by_state(),
        buffer_stocks(),
        market_arrivals(),
        crop_production_national(),
        as287b_state_year(),
        hces_maharashtra_level4(),
        hces_factsheet_tables(),
        online_food_survey(),
        unep_fwi_sectors(),
        openfoodfacts_extract(),
    ]
    reports = {r["dataset"]: r for _, r in results}

    qr_path = PROV / "quality_reports.json"
    existing = json.loads(qr_path.read_text(encoding="utf-8")) \
        if qr_path.exists() else {}
    existing.update(reports)
    qr_path.write_text(json.dumps(existing, indent=2))

    # merge user metadata into the master metadata file
    meta_path = PROV / "dataset_metadata.json"
    master = json.loads(meta_path.read_text(encoding="utf-8")) \
        if meta_path.exists() else []
    by_name = {m.get("dataset_name"): m for m in master}
    user_meta = {_u["dataset_name"]: _u for _u in _user_prov()}
    skip = {"openfoodfacts_extract"}
    for name, rec in user_meta.items():
        if name in skip:
            continue
        merged = {
            "dataset_name": name,
            "source": rec.get("content", ""),
            "publisher": rec.get("publisher", ""),
            "country": "India",
            "license_or_usage_terms": (
                "Government of India publication - parliamentary answer / "
                "official statistics; public dissemination by legislature"
                if rec.get("provenance_type") == "OFFICIAL"
                else "community/Kaggle redistribution; educational use"),
            "download_date": rec.get("download_date"),
            "file_format": "csv/xlsx",
            "sha256": rec.get("sha256"),
            "provenance_type": rec.get("provenance_type"),
        }
        master.append(merged) if name not in by_name else None
    meta_path.write_text(json.dumps(master, indent=2))

    print(f"user datasets normalized: {len(reports)} quality reports, "
          f"{len(master)} total metadata records")


if __name__ == "__main__":
    run_all()
