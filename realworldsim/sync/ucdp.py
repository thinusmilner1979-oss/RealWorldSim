"""UCDP Georeferenced Event Dataset API (free): https://ucdp.uu.se/apidocs/

Battle-related deaths per country over the last 12 months -> conflict intensity.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .http import get_json

# The dataset version string changes with each release; try newest first.
VERSIONS = ["25.1", "24.1", "23.1"]
BASE = "https://ucdpapi.pcr.uu.se/api/gedevents/{ver}?pagesize=1000&page={page}&StartDate={start}"

# UCDP uses Gleditsch-Ward country names; map the ones that differ from Natural Earth names.
NAME_TO_ISO = {
    "Russia (Soviet Union)": "RUS", "Ukraine": "UKR", "Israel": "ISR", "Palestine": "PSE", "Sudan": "SDN",
    "Myanmar (Burma)": "MMR", "Mali": "MLI", "Burkina Faso": "BFA", "Niger": "NER", "DR Congo (Zaire)": "COD",
    "Somalia": "SOM", "Yemen (North Yemen)": "YEM", "Syria": "SYR", "Iraq": "IRQ", "Afghanistan": "AFG",
    "Pakistan": "PAK", "Nigeria": "NGA", "Ethiopia": "ETH", "Mozambique": "MOZ", "Cameroon": "CMR",
    "Haiti": "HTI", "Mexico": "MEX", "Colombia": "COL", "Lebanon": "LBN", "Iran": "IRN", "India": "IND",
    "Philippines": "PHL", "Libya": "LBY", "South Sudan": "SSD", "Central African Republic": "CAF",
    "Chad": "TCD", "Kenya": "KEN", "Uganda": "UGA", "Burundi": "BDI", "Rwanda": "RWA", "Egypt": "EGY",
    "Turkey": "TUR", "Azerbaijan": "AZE", "Armenia": "ARM", "Thailand": "THA", "Indonesia": "IDN",
    "Bangladesh": "BGD", "Brazil": "BRA", "Venezuela": "VEN", "Ecuador": "ECU", "Benin": "BEN", "Togo": "TGO",
    "Tanzania": "TZA", "Senegal": "SEN", "Tunisia": "TUN", "Algeria": "DZA", "Saudi Arabia": "SAU",
}


def intensity_from_deaths(deaths: float) -> float:
    """Map annual battle deaths to a 0..1 intensity (log scale: 100 -> 0.2, 10k -> 0.6, 100k -> 0.9)."""
    import math

    if deaths <= 25:
        return 0.0
    return float(min(1.0, 0.2 + 0.2 * math.log10(deaths / 100)))


def aggregate(events: list[dict], name_map: dict[str, str] | None = None) -> dict[str, dict]:
    name_map = name_map or NAME_TO_ISO
    deaths: dict[str, float] = {}
    for ev in events:
        iso = name_map.get(ev.get("country", ""))
        if not iso:
            continue
        deaths[iso] = deaths.get(iso, 0.0) + float(ev.get("best", 0) or 0)
    return {iso: {"battle_deaths_12m": d, "war_intensity_live": intensity_from_deaths(d)}
            for iso, d in deaths.items()}


def fetch(cache: Path, verbose: bool = False) -> dict:
    start = (date.today() - timedelta(days=365)).isoformat()
    events: list[dict] = []
    for ver in VERSIONS:
        try:
            page = 0
            while True:
                payload = get_json(BASE.format(ver=ver, page=page, start=start))
                events.extend(payload.get("Result", []))
                if not payload.get("NextPageUrl") or page > 200:
                    break
                page += 1
            break
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  ucdp {ver}: {e}")
            events = []
    if not events:
        return {}
    countries = aggregate(events)
    if verbose:
        top = sorted(countries.items(), key=lambda kv: -kv[1]["battle_deaths_12m"])[:8]
        print("  deadliest 12m:", ", ".join(f"{k} {int(v['battle_deaths_12m'])}" for k, v in top))
    return {"countries": countries}
