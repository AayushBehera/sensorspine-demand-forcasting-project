"""Inspect acquired datasets: structure only, no mutation."""
import csv
import io
import zipfile
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

z = zipfile.ZipFile(RAW / "official" / "hces2324_bengaluru.zip")
print("HCES zip entries:")
for i in z.infolist()[:25]:
    print(f"  {i.filename}  {i.file_size//1024}KB")

def head(p, n=2):
    txt = (RAW / p).read_text(encoding="utf-8-sig", errors="replace")
    lines = txt.splitlines()
    print(f"\n{p}: {len(lines)-1} rows")
    for ln in lines[:n]:
        print(" ", ln[:240])

head("community/swiggy_india_restaurants.csv")
head("research/ifct2017_compositions_index.csv")
head("official/unep_food_waste_index_owid.csv", 4)

# India rows in UNEP data
rows = list(csv.DictReader(io.StringIO((RAW / "official/unep_food_waste_index_owid.csv").read_text())))
india = [r for r in rows if r["Entity"] == "India"]
print("\nUNEP India rows:", india)
