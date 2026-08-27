"""Acquire all external datasets into data/raw/<tier>/. Run once per environment."""
import hashlib
import io
import json
import urllib.request
import zipfile
from datetime import date, timezone, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "Mozilla/5.0 (research; sensorspine)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=120).read()


def save(tier: str, name: str, url: str) -> dict:
    d = RAW / tier
    d.mkdir(parents=True, exist_ok=True)
    out = d / name
    blob = fetch(url)
    out.write_bytes(blob)
    rec = {
        "dataset_name": out.stem,
        "source_url": url,
        "download_date": datetime.now(timezone.utc).isoformat(),
        "file_format": out.suffix.lstrip("."),
        "size_bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "provenance_type": {"official": "OFFICIAL", "community": "COMMUNITY",
                            "research": "RESEARCH"}[tier],
    }
    print("saved", tier, name, f"{len(blob)/1048576:.1f}MB")
    return rec


records = []

# 1. OFFICIAL — HCES 2023-24 Bengaluru Urban unit-level microdata
#    (mirror of microdata.gov.in survey extract, hosted by OpenCity/Oorvani)
records.append(save(
    "official", "hces2324_bengaluru.zip",
    "https://data.opencity.in/dataset/d3a6bc19-1a9d-4a72-9b33-990537931a40/"
    "resource/aef9093d-5270-4852-8175-d53629dcfd64/download/"
    "bengaluru_hces_levels_data.zip"))

# 2. COMMUNITY — Swiggy restaurant listings across Indian cities
#    (Kaggle-derived mirror; original: kaggle.com/datasets/swiggy-food-dataset)
records.append(save(
    "community", "swiggy_india_restaurants.csv",
    "https://raw.githubusercontent.com/shashanksingh1717/Swiggy-database/main/database.csv"))

# 3. RESEARCH — IFCT 2017 food composition index (ICMR-NIN; ifct2017 project)
records.append(save(
    "research", "ifct2017_compositions_index.csv",
    "https://raw.githubusercontent.com/ifct2017/ifct2017/main/compositions/index.csv"))

# 4. OFFICIAL-derived — UNEP Food Waste Index via Our World in Data
records.append(save(
    "official", "unep_food_waste_index_owid.csv",
    "https://ourworldindata.org/grapher/food-waste-per-capita.csv?useColumnShortNames=true"))

(RAW / "_provenance.json").write_text(json.dumps(records, indent=2))
print("provenance written:", len(records), "datasets")
