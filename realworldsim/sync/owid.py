"""Our World in Data grapher CSV endpoints (free, no key, CC BY).

One fetcher, many indicators. Each grapher chart can be downloaded as
https://ourworldindata.org/grapher/<slug>.csv with columns Entity, Code, Year, <value>.
We take the latest year per country. Slugs occasionally get renamed, so each field has a
list of candidates and the first that works wins.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from .http import get_text

URL = "https://ourworldindata.org/grapher/{slug}.csv?csvType=full&useColumnShortNames=true"

TWH_PER_MBD = 620.0   # 1 million barrels/day for a year ~ 620 TWh (1 bbl ~ 1.7 MWh)
TWH_PER_BCM = 10.0    # 1 bcm of gas ~ 10 TWh

# field -> (candidate slugs, converter from the CSV value)
INDICATORS: dict[str, tuple[list[str], callable]] = {
    "oil_prod": (["oil-production-by-country"], lambda v: v / TWH_PER_MBD),
    "oil_cons": (["oil-consumption-by-country"], lambda v: v / TWH_PER_MBD),
    "gas_prod": (["gas-production-by-country"], lambda v: v / TWH_PER_BCM),
    "gas_cons": (["gas-consumption-by-country"], lambda v: v / TWH_PER_BCM),
    "mil_spend_gdp": (["military-expenditure-share-gdp", "military-expenditure-as-a-share-of-gdp"], float),
    "population": (["population", "population-with-un-projections"], float),
    "democracy_index": (["liberal-democracy-index", "electoral-democracy-index"], float),
    "food_import_share": (["share-of-food-imports-in-total-merchandise-imports"], lambda v: min(1.0, v / 100)),
}


def parse(csv_text: str, conv, max_year: int | None = None) -> dict[str, tuple[float, int]]:
    """Latest (value, year) per ISO3 code from an OWID grapher CSV."""
    rdr = csv.reader(io.StringIO(csv_text))
    header = next(rdr, None)
    if not header or len(header) < 4:
        return {}
    out: dict[str, tuple[float, int]] = {}
    for row in rdr:
        if len(row) < 4 or len(row[1]) != 3 or row[1].startswith("OWID"):
            continue
        try:
            year = int(row[2])
            val = row[3]
            if val == "":
                continue
            v = conv(float(val))
        except (TypeError, ValueError):
            continue
        if max_year and year > max_year:
            continue
        if row[1] not in out or year > out[row[1]][1]:
            out[row[1]] = (v, year)
    return out


def fetch(cache: Path, verbose: bool = False) -> dict:
    countries: dict[str, dict] = {}
    for field, (slugs, conv) in INDICATORS.items():
        got: dict[str, tuple[float, int]] = {}
        for slug in slugs:
            try:
                got = parse(get_text(URL.format(slug=slug), timeout=120), conv)
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"  owid {slug}: {e}")
                continue
            if got:
                break
        for iso, (v, year) in got.items():
            countries.setdefault(iso, {})[field] = v
            countries[iso][f"{field}_year"] = year
        if verbose:
            print(f"  {field:<18} {len(got)} countries")
    # V-Dem liberal democracy index (0..1, 1 = most democratic) -> model regime (1 = autocracy)
    for v in countries.values():
        if "democracy_index" in v:
            v["regime"] = round(1.0 - v["democracy_index"], 3)
    return {"countries": countries} if countries else {}
