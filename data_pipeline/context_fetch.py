"""Context fetchers: real Bengaluru weather (Open-Meteo ERA5) and the real
Indian public-holiday calendar (python `holidays` package).

Both write to data/processed/ and are used by app/data_generator.py so the
synthetic operational dataset reacts to REAL Indian context. If a fetch
fails, callers fall back to synthetic context and the provenance record
says so.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
# Bengaluru Urban (matches the HCES microdata extract).
LAT, LON = 12.9716, 77.5946
CITY = "bengaluru"

WEATHER_CSV = PROCESSED / "weather" / f"{CITY}_era5_daily.csv"
HOLIDAYS_CSV = PROCESSED / "context" / "india_public_holidays.csv"


def _http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "sensorspine"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def fetch_weather(start: date, end: date) -> dict:
    """Daily mean temperature + precipitation from Open-Meteo ERA5 archive."""
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LAT}&longitude={LON}"
        f"&start_date={start.isoformat()}&end_date={end.isoformat()}"
        "&daily=temperature_2m_mean,precipitation_sum"
        "&timezone=Asia%2FKolkata"
    )
    d = _http_json(url)["daily"]
    lines = ["date,temp_c,precip_mm"]
    for i, ds in enumerate(d["time"]):
        t = d["temperature_2m_mean"][i]
        p = d["precipitation_sum"][i]
        lines.append(f"{ds},{'' if t is None else round(t, 1)},{'' if p is None else round(p, 1)}")
    WEATHER_CSV.parent.mkdir(parents=True, exist_ok=True)
    WEATHER_CSV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    n = len(d["time"])
    print(f"weather: {n} days -> {WEATHER_CSV.name}")
    return {"rows": n, "file": str(WEATHER_CSV), "source": "Open-Meteo ERA5 archive",
            "city": CITY}


def fetch_holidays(years: list[int]) -> dict:
    """Indian public holidays incl. major festivals via the `holidays` package."""
    import holidays as hol

    rows = ["date,name"]
    for y in years:
        for dt, name in sorted(hol.country_holidays("IN", years=[y]).items()):
            safe = name.replace(",", ";")
            rows.append(f"{dt.isoformat()},{safe}")
    HOLIDAYS_CSV.parent.mkdir(parents=True, exist_ok=True)
    HOLIDAYS_CSV.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"holidays: {len(rows)-1} entries -> {HOLIDAYS_CSV.name}")
    return {"rows": len(rows) - 1, "file": str(HOLIDAYS_CSV),
            "source": "python `holidays` package (India)"}


def load_weather(start: date, end: date) -> dict[str, dict]:
    """{iso_date: {temp_c, precip_mm}} from processed CSV; empty if missing."""
    if not WEATHER_CSV.exists():
        return {}
    out: dict[str, dict] = {}
    for ln in WEATHER_CSV.read_text(encoding="utf-8").splitlines()[1:]:
        parts = ln.split(",")
        if len(parts) < 3:
            continue
        ds, t, p = parts[0], parts[1], parts[2]
        if start.isoformat() <= ds <= end.isoformat():
            out[ds] = {
                "temp_c": float(t) if t else None,
                "precip_mm": float(p) if p else None,
            }
    return out


def load_holidays() -> set[str]:
    if not HOLIDAYS_CSV.exists():
        return set()
    return {ln.split(",")[0]
            for ln in HOLIDAYS_CSV.read_text(encoding="utf-8").splitlines()[1:]
            if ln.strip()}


if __name__ == "__main__":
    today = date.today()
    info_w = fetch_weather(today - timedelta(days=400), today)
    info_h = fetch_holidays(sorted({today.year - 1, today.year, today.year + 1}))
    print(json.dumps({"weather": info_w, "holidays": info_h}, indent=2))
