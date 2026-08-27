"""Live weather via Open-Meteo (free, no API key required).

Campus coordinates are not stored in the dataset, so we use representative
Bengaluru points (the operational theatre). Weather is local enough across the
metro that this is a faithful overlay, not a per-rooftop reading.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import date, timedelta

BENGALURU = (12.9716, 77.5946)
DEFAULT_DAYS = 7

# A few named campuses get fixed, plausible Bengaluru coordinates so their
# weather is stable across requests. Anything else derives a deterministic
# offset from its id.
CAMPUS_COORDS: dict[str, tuple[float, float]] = {
    "campus-01": (12.9910, 77.6920),   # Whitefield-ish
    "campus-02": (12.9352, 77.6245),   # Koramangala-ish
    "campus-03": (13.0218, 77.5670),   # Yeshwanthpur-ish
    "campus-04": (12.8960, 77.5960),   # JP Nagar-ish
    "campus-05": (13.0475, 77.6190),   # Hebbal-ish
}


def campus_coords(location_id: str | None) -> tuple[float, float]:
    if location_id and location_id in CAMPUS_COORDS:
        return CAMPUS_COORDS[location_id]
    h = hashlib.sha1(str(location_id or "all").encode()).digest()
    dlat = (h[0] % 50 - 25) * 0.0016
    dlng = (h[1] % 50 - 25) * 0.0016
    return (BENGALURU[0] + dlat, BENGALURU[1] + dlng)


def _num(v):
    try:
        return round(float(v), 2) if v is not None else None
    except (TypeError, ValueError):
        return None


def get_weather(location_id: str | None = None, days: int = DEFAULT_DAYS) -> dict:
    """Return daily weather for the campus (or metro centre).

    Falls back to a clear error payload if the network is unavailable so the
    chat can explain the outage instead of crashing.
    """
    lat, lng = campus_coords(location_id)
    end = date.today()
    start = end - timedelta(days=max(0, int(days) - 1))
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat:.4f}&longitude={lng:.4f}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "wind_speed_10m_max,weather_code"
        "&timezone=Asia%2FKolkata"
        f"&start_date={start.isoformat()}&end_date={end.isoformat()}"
    )
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.load(r).get("daily", {})
    except Exception as e:  # network down / blocked
        return {"source": "open-meteo", "error": str(e),
                "lat": round(lat, 4), "lng": round(lng, 4), "days": []}

    times = data.get("time", [])
    n = len(times)
    out = []
    for i, d in enumerate(times):
        out.append({
            "date": d,
            "temp_max": _num(data.get("temperature_2m_max", [None] * n)[i]),
            "temp_min": _num(data.get("temperature_2m_min", [None] * n)[i]),
            "precip": _num(data.get("precipitation_sum", [None] * n)[i]),
            "wind": _num(data.get("wind_speed_10m_max", [None] * n)[i]),
            "code": _num(data.get("weather_code", [None] * n)[i]),
        })
    return {"source": "open-meteo", "lat": round(lat, 4), "lng": round(lng, 4), "days": out}
