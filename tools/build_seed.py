#!/usr/bin/env python3
"""Build the bundled seed dataset from Natural Earth (public domain).

Downloads the 50m admin-0 countries GeoJSON, keeps recognised states, and writes:

  realworldsim/data/countries.json  - one record per country (ISO3, name, region,
                                      population, GDP, income group, centroid)
  realworldsim/data/world.geojson   - slimmed geometry for the map (3-decimal coords)

Run:  python tools/build_seed.py [path/to/ne_50m_admin_0_countries.geojson]
If no path is given the file is downloaded from GitHub.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_50m_admin_0_countries.geojson"
)
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "realworldsim" / "data"

INCOME = {
    "1. High income: OECD": "high_oecd",
    "2. High income: nonOECD": "high",
    "3. Upper middle income": "upper_middle",
    "4. Lower middle income": "lower_middle",
    "5. Low income": "low",
}


# Entities Natural Earth marks disputed/indeterminate that we model anyway.
EXTRA = {"KOS": "XKX", "PSX": "PSE", "ISR": "ISR"}  # ADM0_A3 -> code used by World Bank


def iso3(p: dict) -> str:
    if p["ADM0_A3"] in EXTRA:
        return EXTRA[p["ADM0_A3"]]
    code = p["ISO_A3"]
    if code == "-99":
        code = p["ISO_A3_EH"]
    return code


def keep(p: dict) -> bool:
    if p["ADM0_A3"] in EXTRA:
        return True
    if p["TYPE"] in ("Dependency", "Disputed", "Indeterminate"):
        return False
    code = iso3(p)
    if code == "-99" or len(code) != 3:
        return False  # Somaliland, N. Cyprus
    if p["GDP_MD"] is None or p["GDP_MD"] <= 0:
        return False  # Vatican
    adm, sov = p["ADM0_A3"], p["SOV_A3"]
    if adm == sov:
        return True
    # Main unit of a sovereign group (USA/US1, GBR/GB1, CHN/CH1 ...): keep.
    # Dependencies modelled as separate units (Hong Kong, Greenland, Aruba): drop.
    return sov.endswith("1") and sov[:2] == adm[:2]


def round_coords(obj, nd=3):
    if isinstance(obj, (int, float)):
        return round(obj, nd)
    return [round_coords(o, nd) for o in obj]


def main(src: str | None) -> None:
    if src:
        raw = Path(src).read_bytes()
    else:
        print("downloading", NE_URL)
        with urllib.request.urlopen(NE_URL, timeout=120) as r:
            raw = r.read()
    gj = json.loads(raw)

    countries, features = [], []
    for f in gj["features"]:
        p = f["properties"]
        if not keep(p):
            continue
        code = iso3(p)
        countries.append(
            {
                "iso3": code,
                "name": p["NAME"],
                "name_long": p["NAME_LONG"],
                "continent": p["CONTINENT"],
                "region": p["REGION_UN"],
                "subregion": p["SUBREGION"],
                "region_wb": p["REGION_WB"],
                "income_group": INCOME.get(p["INCOME_GRP"], "unknown"),
                "economy_class": p["ECONOMY"],
                "population": int(p["POP_EST"]),
                "gdp_usd_bn": round(p["GDP_MD"] / 1000.0, 3),
                "gdp_year": p["GDP_YEAR"],
                "fips": p.get("FIPS_10") if p.get("FIPS_10") not in (None, "-99") else None,
                "lon": round(p["LABEL_X"], 3),
                "lat": round(p["LABEL_Y"], 3),
            }
        )
        features.append(
            {
                "type": "Feature",
                "id": code,
                "properties": {"iso3": code, "name": p["NAME"]},
                "geometry": {
                    "type": f["geometry"]["type"],
                    "coordinates": round_coords(f["geometry"]["coordinates"]),
                },
            }
        )

    countries.sort(key=lambda c: c["iso3"])
    features.sort(key=lambda f: f["id"])
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "countries.json").write_text(
        json.dumps(
            {
                "source": "Natural Earth 50m admin-0 (public domain)",
                "note": "Seed values only. Run `rws sync` to replace with live World Bank / IMF data.",
                "countries": countries,
            },
            indent=1,
        )
    )
    (DATA / "world.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
    )
    print(f"wrote {len(countries)} countries")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
