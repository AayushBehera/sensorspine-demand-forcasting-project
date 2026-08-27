"""Copy user-collected datasets into data/raw/<tier>/ with sha256 provenance.

Nothing is interpreted here - that happens in normalize.py. This only
preserves originals + records where they came from.
"""
import hashlib
import shutil
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

COPIES = [
    # (source path or None-if-kagglehub, tier, dest name, meta overrides)
    (r"C:\Users\aayus\Downloads\RS-Session-251-AU3123-Annexure-I.csv",
     "official", "rs251_monthly_food_inflation.csv",
     {"dataset_name": "rs251_monthly_food_inflation",
      "source": "Rajya Sabha unstarred question AU3123 annexure (Session 251)",
      "publisher": "Rajya Sabha Secretariat / Ministry of Statistics",
      "content": "Monthly y-o-y food-price inflation %, India, 2014-2020",
      "provenance_type": "OFFICIAL"}),
    (r"C:\Users\aayus\Downloads\RS_249_AU2319.csv",
     "official", "rs249_food_processing_factories_by_state.csv",
     {"dataset_name": "rs249_food_processing_factories_by_state",
      "source": "Rajya Sabha answer AU2319 (Session 249)",
      "publisher": "Rajya Sabha Secretariat / Ministry of FPI",
      "content": "Registered vs operating food-processing factories by State/UT",
      "provenance_type": "OFFICIAL"}),
    (r"C:\Users\aayus\Downloads\RS_Session_256_AU_392_B.csv",
     "official", "rs256_avg_foodgrain_stocks.csv",
     {"dataset_name": "rs256_avg_foodgrain_stocks",
      "source": "Rajya Sabha answer AU392 (Session 256)",
      "publisher": "Rajya Sabha Secretariat / DFPD",
      "content": "Average foodgrain stock (MT) in central pool godowns by year",
      "provenance_type": "OFFICIAL"}),
    (r"C:\Users\aayus\Downloads\Table_5.5_Total_market_arrivals_foodgrainsandnonfoodgrains.csv",
     "official", "table5_5_market_arrivals_district_year.csv",
     {"dataset_name": "market_arrivals_district_year",
      "source": "Statistical abstract Table 5.5 - total market arrivals of "
                "foodgrains and non-foodgrains (Punjab districts)",
      "publisher": "State statistics (Agmarknet-derived)",
      "content": "District x Year market arrival quantities, 2007-2018",
      "provenance_type": "OFFICIAL"}),
    (r"C:\Users\aayus\Downloads\RS_Session_265_AU_2108_D_to_E.csv",
     "official", "rs265_crop_production_national.csv",
     {"dataset_name": "crop_production_national",
      "source": "Rajya Sabha answer AU2108 D-E (Session 265)",
      "publisher": "Rajya Sabha Secretariat / Ministry of Agriculture",
      "content": "National crop production in million tonnes",
      "provenance_type": "OFFICIAL"}),
    (r"C:\Users\aayus\Downloads\RS_249_AS287-B.csv",
     "official", "rs249_as287b_state_year_unverified_metric.csv",
     {"dataset_name": "rs249_as287b_state_year",
      "source": "Rajya Sabha answer AS287-B (Session 249)",
      "publisher": "Rajya Sabha Secretariat",
      "content": "State x year quantities; exact metric not verifiable from "
                 "the extract alone - stored with interpretation_uncertain flag",
      "provenance_type": "OFFICIAL"}),
    (r"C:\Users\aayus\Downloads\04b689a4-f3bb-4271-b14c-ff492efcc8c7.csv",
     "official", "hces2023_maharashtra_level4_unit_data.csv",
     {"dataset_name": "hces2023_maharashtra_level4",
      "source": "data.gov.in HCES 2022-23 unit-level export (GUID filename)",
      "publisher": "MoSPI via data.gov.in",
      "content": "HCES 2022 Level-4 rows, 2,516 urban Maharashtra households "
                 "(generic Col1-Col20 headers; meaning not decodable without "
                 "official Level-4 layout - preserved verbatim)",
      "provenance_type": "OFFICIAL"}),
    (r"C:\Users\aayus\Downloads\HCES.xlsx",
     "official", "hces2324_factsheet_tables.xlsx",
     {"dataset_name": "hces2324_factsheet_tables",
      "source": "MoSPI HCES 2022-23/2023-24 factsheet workbook",
      "publisher": "Ministry of Statistics & PI",
      "content": "%Composition of MPCE, trend in consumption levels, MPCE "
                 "levels across survey years (rural/urban)",
      "provenance_type": "OFFICIAL"}),
    (r"C:\Users\aayus\AppData\Local\Temp\onlinefoods.csv",
     "community", "onlinefoods_bangalore_survey.csv",
     {"dataset_name": "onlinefoods_bangalore_survey",
      "source": "Kaggle sudarshan24byte/online-food-dataset (identical copy "
                "supplied by user)",
      "publisher": "community; original survey unknown",
      "content": "~388 Bangalore respondents: demographics + online food "
                 "order outcome + feedback sentiment + pincode",
      "provenance_type": "COMMUNITY"}),
    (None, "research", "unep_food_waste_by_country_kaggle.csv",
     {"dataset_name": "unep_fwi_by_country_sectors",
      "source": "Kaggle joebeachcapital/food-waste = UNEP Food Waste Index "
                "country table (via kagglehub)",
      "publisher": "UNEP (Kaggle republish)",
      "content": "214 countries: household/retail/FOOD-SERVICE waste "
                 "kg/capita/year + tonnes/year; India = 94 combined / 28 "
                 "food service",
      "provenance_type": "RESEARCH"}),
    (r"C:\Users\aayus\Downloads\en.openfoodfacts.org.products.tsv-selected-columns.csv",
     "community", "openfoodfacts_selected_columns_EMPTY.csv",
     {"dataset_name": "openfoodfacts_extract",
      "content": "124 rows, 0 usable product names -> UNUSABLE extract",
      "status": "REJECTED - empty sample; kept only as evidence",
      "provenance_type": "COMMUNITY"}),
]


def main() -> None:
    records_path = RAW / "_user_provenance.json"
    records = json.loads(records_path.read_text(encoding="utf-8")) \
        if records_path.exists() else []
    seen = {m["dataset_name"] for m in records}

    for src, tier, dest, meta in COPIES:
        d = RAW / tier
        d.mkdir(parents=True, exist_ok=True)
        out = d / dest
        blob = None
        if src is not None:
            src_p = Path(src)
            if not src_p.exists():
                print("MISSING source:", src)
                continue
            shutil.copyfile(src_p, out)
            blob = out.read_bytes()
        else:
            # kagglehub-sourced file
            kh = Path(r"C:\Users\aayus\.cache\kagglehub\datasets"
                      r"\joebeachcapital\food-waste\versions\1"
                      r"\Food Waste data and research - by country.csv")
            shutil.copyfile(kh, out)
            blob = out.read_bytes()
        rec = {
            **meta,
            "file": str(out.relative_to(ROOT)),
            "download_date": datetime.now(timezone.utc).isoformat(),
            "size_bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        if rec["dataset_name"] not in seen:
            records.append(rec)
        else:
            records = [rec if m["dataset_name"] == rec["dataset_name"] else m
                       for m in records]
        print("copied", tier, dest)

    records_path.write_text(json.dumps(records, indent=2))
    print(f"provenance: {len(records)} user datasets recorded")


if __name__ == "__main__":
    main()
